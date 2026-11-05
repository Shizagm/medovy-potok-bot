"""Character portraits, single-occupancy landing, and master-controlled NPCs."""
from collections import deque
from pathlib import Path
import io,re,sqlite3,warnings
from PIL import Image,ImageOps,UnidentifiedImageError

MAX_UPLOAD=5*1024*1024
MAX_PIXELS=12_000_000

def normalize_portrait(raw):
    if not isinstance(raw,bytes) or not raw or len(raw)>MAX_UPLOAD:raise ValueError('Портрет: JPEG или PNG размером до 5 МБ.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('PNG','JPEG') or getattr(source,'is_animated',False):raise ValueError('Нужно статичное изображение JPEG или PNG.')
                if source.width*source.height>MAX_PIXELS:raise ValueError('Изображение слишком большое: максимум 12 миллионов пикселей.')
                source.load();im=ImageOps.exif_transpose(source).convert('RGBA')
                im=ImageOps.fit(im,(128,128),method=Image.Resampling.LANCZOS)
                background=Image.new('RGBA',im.size,(62,46,75,255));background.alpha_composite(im)
                out=io.BytesIO();background.convert('RGB').save(out,format='PNG');return out.getvalue()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise ValueError('Не удалось прочитать портрет. Пришли обычный JPEG или PNG до 5 МБ.') from None

class TokensMixin:
    def token_schema(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS character_tokens(uid INTEGER PRIMARY KEY REFERENCES players(uid),png BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS map_npcs(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('npc','monster')),area TEXT NOT NULL,x INTEGER NOT NULL,y INTEGER NOT NULL,size INTEGER NOT NULL DEFAULT 1,png BLOB);
        CREATE INDEX IF NOT EXISTS map_npc_area ON map_npcs(area);
        ''')
    def token_set(self,uid,raw):
        self.player(uid)
        try:png=normalize_portrait(raw)
        except ValueError as exc:raise self.error(str(exc))
        with self.tx():self.db.execute('INSERT INTO character_tokens VALUES(?,?) ON CONFLICT(uid) DO UPDATE SET png=excluded.png',(uid,png))
        return png
    def token_clear(self,uid):
        self.player(uid)
        with self.tx():self.db.execute('DELETE FROM character_tokens WHERE uid=?',(uid,))
    def token_get(self,uid):
        row=self.db.execute('SELECT png FROM character_tokens WHERE uid=?',(uid,)).fetchone();return row[0] if row else None
    def npc_token_set(self,nid,raw):
        if not self.db.execute('SELECT 1 FROM map_npcs WHERE id=?',(nid,)).fetchone():raise self.error('Такого НПС нет.')
        try:png=normalize_portrait(raw)
        except ValueError as exc:raise self.error(str(exc))
        self.db.execute('UPDATE map_npcs SET png=? WHERE id=?',(png,nid))
    def map_npc_cells(self,exclude=None):
        cells=set()
        for row in self.db.execute('SELECT * FROM map_npcs'):
            if row['id']==exclude:continue
            for y in range(row['y'],row['y']+row['size']):
                for x in range(row['x'],row['x']+row['size']):cells.add((row['area'],x,y))
        return cells
    def map_occupied(self,node,exclude=None):
        return bool(self.db.execute('SELECT 1 FROM map_positions m JOIN players p ON p.uid=m.uid WHERE m.on_map=1 AND p.approved=1 AND m.area=? AND m.x=? AND m.y=? AND m.uid!=?',(*node,exclude if exclude is not None else -1)).fetchone())
    def map_can_stop(self,uid,node,ghost=False,data=None):
        return self.map_passable(node,ghost,data) and not self.map_occupied(node,uid)
    def map_find_free(self,uid,start,ghost=False):
        data=self.map_data();data['_npc_cells']=self.map_npc_cells()
        if not self.map_passable(start,ghost,data):
            from map_rules import coord
            sp=data['spawn'];start=(sp['area'],*coord(sp['cell']))
        if not self.map_passable(start,ghost,data):return None
        queue=deque([start]);seen={start}
        occupied={(r['area'],r['x'],r['y']) for r in self.db.execute('SELECT area,x,y FROM map_positions WHERE on_map=1 AND uid!=?',(uid,))}
        while queue:
            node=queue.popleft()
            if node not in occupied:return node
            for nxt in self.map_neighbors(node,ghost,data):
                if nxt not in seen:seen.add(nxt);queue.append(nxt)
        return None
    def map_migrate_occupancy(self):
        cols={r[1] for r in self.db.execute('PRAGMA table_info(map_positions)')}
        if 'on_map' not in cols:self.db.execute('ALTER TABLE map_positions ADD COLUMN on_map INTEGER NOT NULL DEFAULT 0')
        if self.meta_value('map_occupancy_v9')!='1':
            with self.tx():
                self.db.execute('UPDATE map_positions SET on_map=0')
                rows=self.db.execute('SELECT m.*,p.dead FROM map_positions m JOIN players p ON p.uid=m.uid WHERE p.approved=1 ORDER BY m.uid').fetchall()
                for row in rows:
                    dest=self.map_find_free(row['uid'],(row['area'],row['x'],row['y']),bool(row['dead']))
                    if dest:
                        self.db.execute('UPDATE map_positions SET area=?,x=?,y=?,on_map=1,rev=rev+1 WHERE uid=?',(*dest,row['uid']))
                    else:self.db.execute('UPDATE map_positions SET rev=rev+1 WHERE uid=?',(row['uid'],))
                self.db.execute("INSERT OR REPLACE INTO meta VALUES('map_occupancy_v9','1')")
        self.db.execute('CREATE UNIQUE INDEX IF NOT EXISTS map_single_occupancy ON map_positions(area,x,y) WHERE on_map=1')
    def map_enter(self,uid):
        with self.tx():
            p=self.player(uid)
            if p['paused']:raise self.error('Участие приостановлено.')
            pos=self.map_position(uid)
            if pos['on_map']:return pos
            from map_rules import coord
            sp=self.map_data()['spawn'];dest=self.map_find_free(uid,(sp['area'],*coord(sp['cell'])),bool(p['dead']))
            if not dest:raise self.error('Свободных клеток сейчас нет. Герой ожидает у портала; попробуй позже.')
            self.db.execute('UPDATE map_positions SET area=?,x=?,y=?,on_map=1,rev=rev+1 WHERE uid=?',(*dest,uid))
            return self.map_position(uid)
    def map_after_resurrection(self,uid):
        pos=self.map_position(uid)
        if pos['on_map'] and self.map_can_stop(uid,(pos['area'],pos['x'],pos['y'])):return
        dest=self.map_find_free(uid,(pos['area'],pos['x'],pos['y']))
        self.db.execute('UPDATE map_positions SET on_map=0,rev=rev+1 WHERE uid=?',(uid,))
        if dest:
            self.db.execute('UPDATE map_positions SET area=?,x=?,y=?,on_map=1 WHERE uid=?',(*dest,uid))
            self.notify(uid,'После возвращения тебя перенесло в ближайшее доступное место: прежняя клетка недоступна живому герою.')
        else:self.notify(uid,'Герой жив, но свободного места на карте нет. Ожидай у портала и нажми «Войти на карту».')
    def map_entity_set(self,nid,kind,area,value,size,name):
        from map_rules import coord
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,23}',nid) or kind not in ('npc','monster') or type(size) is not int or not 1<=size<=4 or not 1<=len(name)<=80:raise self.error('НПС: ID латиницей, тип npc/monster, размер 1–4 клетки, имя до 80 символов.')
        try:x,y=coord(value)
        except ValueError as exc:raise self.error(str(exc))
        data=self.map_data();f=data['floors'].get(area)
        if not f or x+size>len(f['rows'][0]) or y+size>len(f['rows']):raise self.error('НПС выходит за границы этажа.')
        wanted={(area,xx,yy) for yy in range(y,y+size) for xx in range(x,x+size)}
        if any(f['rows'][yy][xx]=='#' for _,xx,yy in wanted):raise self.error('НПС нельзя ставить в стену.')
        if any(not d['open'] and (d['area'],*coord(d['cell'])) in wanted for d in data.get('doors',{}).values()):raise self.error('На клетке закрытая дверь.')
        with self.tx():
            if not self.db.execute('SELECT 1 FROM map_npcs WHERE id=?',(nid,)).fetchone() and self.db.execute('SELECT count(*) FROM map_npcs').fetchone()[0]>=100:raise self.error('На карте уже 100 НПС и монстров.')
            if wanted & self.map_npc_cells(exclude=nid) or any(self.map_occupied(n) for n in wanted):raise self.error('Место для НПС занято.')
            self.db.execute('INSERT INTO map_npcs(id,name,kind,area,x,y,size) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,area=excluded.area,x=excluded.x,y=excluded.y,size=excluded.size',(nid,name,kind,area,x,y,size))
            if nid=='roy' and not self.db.execute('SELECT png FROM map_npcs WHERE id=?',(nid,)).fetchone()[0]:
                portrait=Path(__file__).parent/'assets/roy-original.jpg'
                if portrait.exists():self.npc_token_set(nid,portrait.read_bytes())
            self.db.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='map_world_rev'")
    def map_entity_remove(self,nid):
        with self.tx():
            if not self.db.execute('DELETE FROM map_npcs WHERE id=?',(nid,)).rowcount:raise self.error('Такого НПС нет.')
            self.db.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='map_world_rev'")
