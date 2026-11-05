"""Persistent grid map; movement and trade proximity use server-side paths."""
from collections import deque
from datetime import timedelta
from pathlib import Path
import json,re,time

def coord(value):
    m=re.fullmatch(r'([A-Z])([1-9][0-9]?)',str(value).strip().upper())
    if not m:raise ValueError('Клетка: латинская буква и номер, например L16.')
    return ord(m[1])-65,int(m[2])-1

def cell(x,y):return chr(65+x)+str(y+1)

class MapMixin:
    def map_schema(self):
        self.token_schema()
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS map_positions(uid INTEGER PRIMARY KEY REFERENCES players(uid),area TEXT NOT NULL,x INTEGER NOT NULL,y INTEGER NOT NULL,remaining INTEGER NOT NULL DEFAULT 0,epoch TEXT,rev INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS map_reveals(area TEXT NOT NULL,x INTEGER NOT NULL,y INTEGER NOT NULL,PRIMARY KEY(area,x,y));
        CREATE TABLE IF NOT EXISTS map_orders(id INTEGER PRIMARY KEY,uid INTEGER NOT NULL REFERENCES players(uid),area TEXT NOT NULL,x INTEGER NOT NULL,y INTEGER NOT NULL,start_rev INTEGER NOT NULL,world_rev INTEGER NOT NULL,created INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',receipt TEXT);
        ''')
        if not self.meta_value('map_definition'):
            path=Path(__file__).parent/'maps/tavern.json'
            data=json.loads(path.read_text(encoding='utf-8'));self.map_validate(data)
            self.db.execute("INSERT INTO meta VALUES('map_definition',?)",(json.dumps(data,ensure_ascii=False),))
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('map_active','0')")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('map_world_rev','0')")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('map_weekly','0')")
        self.map_migrate_occupancy()

    def map_validate(self,data):
        if not isinstance(data,dict) or data.get('cell_ft')!=5:raise self.error('Карта должна использовать клетки по 5 футов.')
        if not isinstance(data.get('name'),str) or not 1<=len(data['name'])<=100:raise self.error('Название карты: до 100 символов.')
        if len(data.get('doors',{}))>100 or len(data.get('landmarks',{}))>8 or len(data.get('links',[]))>30:raise self.error('Слишком много дверей, ориентиров или переходов.')
        floors=data.get('floors',{})
        if not isinstance(floors,dict) or not 1<=len(floors)<=8:raise self.error('Нужно от 1 до 8 этажей.')
        for area,f in floors.items():
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,15}',area):raise self.error('Неверное имя этажа.')
            if not isinstance(f.get('name'),str) or not 1<=len(f['name'])<=60:raise self.error('Название этажа: до 60 символов.')
            rows=f.get('rows',[])
            if not 1<=len(rows)<=40 or not isinstance(rows[0],str) or not 1<=len(rows[0])<=26:raise self.error('Размер этажа: максимум 26×40.')
            if any(not isinstance(r,str) or len(r)!=len(rows[0]) or set(r)-set('.#') for r in rows):raise self.error('Клетки этажа: . — пол, # — стена; строки одной длины.')
        def point(area,value):
            try:x,y=coord(value);rows=floors[area]['rows']
            except (ValueError,KeyError,TypeError):raise self.error('Неверная точка карты.')
            if not 0<=y<len(rows) or not 0<=x<len(rows[0]) or rows[y][x]!='.':raise self.error('Точка должна стоять на полу.')
        spawn=data.get('spawn',{});point(spawn.get('area'),spawn.get('cell'))
        if floors[spawn['area']].get('fog'):raise self.error('Портал появления не может быть под туманом.')
        occupied=set()
        for did,d in data.get('doors',{}).items():
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,20}',did):raise self.error('Неверное имя двери.')
            point(d['area'],d['cell']);key=(d['area'],d['cell'])
            if key in occupied or key==(spawn['area'],spawn['cell']):raise self.error('Двери не должны пересекаться или занимать портал.')
            occupied.add(key)
            if type(d.get('open')) is not bool:raise self.error('У двери нужно open: true/false.')
        for link in data.get('links',[]):
            for area,value in (link['a'],link['b']):point(area,value)
        for key,landmark in data.get('landmarks',{}).items():
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,20}',key) or not isinstance(landmark.get('name'),str) or not 1<=len(landmark['name'])<=40:raise self.error('Неверное имя ориентира.')
            point(landmark['area'],landmark['cell'])

    def map_data(self):return json.loads(self.meta_value('map_definition'))
    def map_enabled(self):return self.meta_value('map_active')=='1'
    def map_save(self,data):
        self.map_validate(data)
        self.db.execute("UPDATE meta SET value=? WHERE key='map_definition'",(json.dumps(data,ensure_ascii=False),))
        self.db.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='map_world_rev'")
    def map_enable(self,on):
        if on not in (0,1):raise self.error('Нужно 0 или 1.')
        with self.tx():
            self.db.execute("UPDATE meta SET value=? WHERE key='map_active'",(str(on),))
            self.db.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='map_world_rev'")
    def map_known(self,area,x,y,data=None):
        data=data or self.map_data();f=data['floors'].get(area)
        if not f or not 0<=y<len(f['rows']) or not 0<=x<len(f['rows'][0]):return False
        return not f.get('fog') or bool(self.db.execute('SELECT 1 FROM map_reveals WHERE area=? AND x=? AND y=?',(area,x,y)).fetchone())
    def map_passable(self,node,ghost=False,data=None):
        data=data or self.map_data();area,x,y=node
        if not self.map_known(area,x,y,data):return False
        blockers=data.get('_npc_cells')
        if blockers is None:blockers=self.map_npc_cells()
        if node in blockers:return False
        if ghost:return True
        if data['floors'][area]['rows'][y][x]=='#':return False
        return not any(d['area']==area and coord(d['cell'])==(x,y) and not d['open'] for d in data.get('doors',{}).values())
    def map_position(self,uid):
        p=self.player(uid)
        row=self.db.execute('SELECT * FROM map_positions WHERE uid=?',(uid,)).fetchone()
        if not row:
            with self.tx():
                spawn=self.map_data()['spawn'];x,y=coord(spawn['cell'])
                dest=self.map_find_free(uid,(spawn['area'],x,y),bool(p['dead']))
                area,xx,yy=dest if dest else (spawn['area'],x,y)
                self.db.execute('INSERT INTO map_positions(uid,area,x,y,on_map) VALUES(?,?,?,?,?)',(uid,area,xx,yy,int(dest is not None)))
            row=self.db.execute('SELECT * FROM map_positions WHERE uid=?',(uid,)).fetchone()
        return dict(row)
    def map_neighbors(self,node,ghost,data):
        area,x,y=node
        for dx,dy in ((0,-1),(-1,0),(1,0),(0,1),(-1,-1),(1,-1),(-1,1),(1,1)):
            nxt=(area,x+dx,y+dy)
            if not self.map_passable(nxt,ghost,data):continue
            if dx and dy and not ghost and (not self.map_passable((area,x+dx,y),False,data) or not self.map_passable((area,x,y+dy),False,data)):continue
            yield nxt
        for link in data.get('links',[]):
            a=(link['a'][0],*coord(link['a'][1]));b=(link['b'][0],*coord(link['b'][1]))
            if node==a and self.map_passable(b,ghost,data):yield b
            if node==b and self.map_passable(a,ghost,data):yield a
    def map_path(self,start,target,ghost=False):
        data=self.map_data();data['_npc_cells']=self.map_npc_cells()
        if not self.map_passable(target,ghost,data):raise self.error('Клетка закрыта, занята стеной или скрыта туманом.')
        if not self.map_passable(start,ghost,data):raise self.error('Текущая клетка стала недоступна. Мастер должен переставить героя.')
        queue=deque([start]);prev={start:None}
        while queue:
            node=queue.popleft()
            if node==target:
                path=[]
                while node is not None:path.append(node);node=prev[node]
                return path[::-1]
            for nxt in self.map_neighbors(node,ghost,data):
                if nxt not in prev:prev[nxt]=node;queue.append(nxt)
        raise self.error('Нет открытого пути: проверь двери и лестницы.')
    def map_grant(self,uid,epoch=None):
        with self.tx():
            p=self.player(uid)
            if p['paused']:raise self.error('Участие приостановлено.')
            c=self.char_data(uid)
            if c['speed_ft'] is None:raise self.error('Сначала подтвердите скорость в карточке.')
            pos=self.map_position(uid)
            if epoch and pos['epoch']==epoch:return False
            self.db.execute('UPDATE map_positions SET remaining=?,epoch=?,rev=rev+1 WHERE uid=?',(c['speed_ft']//5,epoch or pos['epoch'],uid))
            return True
    def map_prepare(self,uid,area,value):
        with self.tx():
            p=self.player(uid)
            if p['paused']:raise self.error('Участие приостановлено.')
            pos=self.map_position(uid)
            if not pos['on_map']:raise self.error('Герой ждёт у портала. Нажми «Войти на карту», когда освободится место.')
            if area not in self.map_data()['floors']:raise self.error('Неизвестный этаж.')
            try:x,y=coord(value)
            except ValueError as exc:raise self.error(str(exc))
            if self.map_occupied((area,x,y),uid):raise self.error('Клетка занята другим персонажем: пройти через неё можно, остановиться нельзя.')
            path=self.map_path((pos['area'],pos['x'],pos['y']),(area,x,y),bool(p['dead']))
            if len(path)==1:raise self.error('Ты уже в этой клетке.')
            if pos['remaining']<=0:raise self.error('Нет передвижения. Его выдаёт мастер или новый недельный ход.')
            used=min(len(path)-1,pos['remaining'])
            while used>0 and not self.map_can_stop(uid,path[used],bool(p['dead'])):used-=1
            if used==0:raise self.error('Не хватает движения, чтобы пройти занятую клетку и остановиться на свободной.')
            dest=path[used]
            self.db.execute("UPDATE map_orders SET status='cancelled' WHERE uid=? AND status='pending'",(uid,))
            cur=self.db.execute('INSERT INTO map_orders(uid,area,x,y,start_rev,world_rev,created) VALUES(?,?,?,?,?,?,?)',(uid,*dest,pos['rev'],int(self.meta_value('map_world_rev')),int(time.time())))
            return dict(id=cur.lastrowid,destination=dest,requested=(area,x,y),cost=used,total=len(path)-1,path=path[:used+1],remaining=pos['remaining']-used)
    def map_commit(self,uid,oid):
        with self.tx():
            row=self.db.execute('SELECT * FROM map_orders WHERE id=?',(oid,)).fetchone()
            if not row or row['uid']!=uid:raise self.error('Чужое перемещение.')
            if row['status']=='done':return json.loads(row['receipt']),True
            p=self.player(uid);pos=self.map_position(uid)
            if p['paused']:raise self.error('Участие приостановлено.')
            if not pos['on_map']:raise self.error('Герой не на карте.')
            if row['status']!='pending' or int(time.time())-row['created']>600:raise self.error('Маршрут истёк. Выбери направление заново.')
            if pos['rev']!=row['start_rev'] or row['world_rev']!=int(self.meta_value('map_world_rev')):raise self.error('Положение, запас движения или карта изменились. Построй маршрут заново.')
            dest=(row['area'],row['x'],row['y'])
            if not self.map_can_stop(uid,dest,bool(p['dead'])):raise self.error('Клетку уже заняли или она закрыта. Выбери другой маршрут; движение не потрачено.')
            path=self.map_path((pos['area'],pos['x'],pos['y']),dest,bool(p['dead']));cost=len(path)-1
            if not 1<=cost<=pos['remaining']:raise self.error('Не хватает передвижения.')
            receipt=dict(area=dest[0],cell=cell(dest[1],dest[2]),cost=cost,remaining=pos['remaining']-cost)
            self.db.execute('UPDATE map_positions SET area=?,x=?,y=?,remaining=remaining-?,rev=rev+1 WHERE uid=?',(*dest,cost,uid))
            self.db.execute("UPDATE map_orders SET status='done',receipt=? WHERE id=?",(json.dumps(receipt),oid))
            self.log(uid,'movement',0,f'{dest[0]} {receipt["cell"]}; {cost} клеток')
            return receipt,False
    def map_adjacent(self,a,b):
        pa=self.map_position(a);pb=self.map_position(b)
        if not pa['on_map'] or not pb['on_map']:return False
        n1=(pa['area'],pa['x'],pa['y']);n2=(pb['area'],pb['x'],pb['y'])
        if not self.map_passable(n1) or not self.map_passable(n2):return False
        if n1==n2:return True
        return n1[0]==n2[0] and n2 in set(self.map_neighbors(n1,False,self.map_data()))
    def map_trade_check(self,a,b):
        if self.map_enabled() and not self.map_adjacent(a,b):raise self.error('Для сделки герои должны быть вплотную на одном этаже. Открой карту и подойди.')
    def map_set_position(self,uid,area,value):
        with self.tx():
            p=self.player(uid)
            try:x,y=coord(value)
            except ValueError as exc:raise self.error(str(exc))
            if not self.map_can_stop(uid,(area,x,y),bool(p['dead'])):raise self.error('Нельзя поставить героя: клетка занята, закрыта или скрыта.')
            self.map_position(uid)
            self.db.execute('UPDATE map_positions SET area=?,x=?,y=?,on_map=1,rev=rev+1 WHERE uid=?',(area,x,y,uid))
            self.log(uid,'map_placement',0,f'Мастер: {area} {cell(x,y)}')
    def map_door(self,did,on):
        with self.tx():
            data=self.map_data()
            if did not in data.get('doors',{}) or on not in (0,1):raise self.error('Неизвестная дверь или состояние.')
            d=data['doors'][did];x,y=coord(d['cell'])
            if not on and self.db.execute('SELECT 1 FROM map_positions m JOIN players p ON p.uid=m.uid WHERE m.on_map=1 AND area=? AND x=? AND y=? AND p.dead=0',(d['area'],x,y)).fetchone():raise self.error('Нельзя закрыть дверь на живом персонаже.')
            if not on and (d['area'],x,y) in self.map_npc_cells():raise self.error('Нельзя закрыть дверь на НПС или монстре.')
            d['open']=bool(on);self.map_save(data)
    def map_reveal(self,area,first,last):
        with self.tx():
            data=self.map_data()
            if area not in data['floors']:raise self.error('Неизвестный этаж.')
            try:x1,y1=coord(first);x2,y2=coord(last)
            except ValueError as exc:raise self.error(str(exc))
            f=data['floors'][area]
            if not (0<=x1<=x2<len(f['rows'][0]) and 0<=y1<=y2<len(f['rows'])):raise self.error('Неверный прямоугольник раскрытия.')
            for y in range(y1,y2+1):
                for x in range(x1,x2+1):self.db.execute('INSERT OR IGNORE INTO map_reveals VALUES(?,?,?)',(area,x,y))
            self.db.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='map_world_rev'")
    def map_load(self):
        with self.tx():
            db_file=self.db.execute('PRAGMA database_list').fetchone()['file']
            private=Path(db_file).parent/'private-map.json'
            source=private if private.exists() else Path(__file__).parent/'maps/tavern.json'
            if source.is_symlink() or source.stat().st_size>200000:raise self.error('Файл карты слишком большой или является ссылкой.')
            data=json.loads(source.read_text(encoding='utf-8'));self.map_validate(data)
            old=self.map_data();self.map_save(data)
            for n in self.db.execute('SELECT * FROM map_npcs'):
                f=data['floors'].get(n['area'])
                if not f or n['x']+n['size']>len(f['rows'][0]) or n['y']+n['size']>len(f['rows']) or any(f['rows'][yy][xx]=='#' for yy in range(n['y'],n['y']+n['size']) for xx in range(n['x'],n['x']+n['size'])):raise self.error('Новая схема перекрывает НПС. Переставь или убери его до загрузки.')
                occupied={(n['area'],xx,yy) for yy in range(n['y'],n['y']+n['size']) for xx in range(n['x'],n['x']+n['size'])}
                if any(not d['open'] and (d['area'],*coord(d['cell'])) in occupied for d in data.get('doors',{}).values()):raise self.error('Новая схема закрывает дверь на НПС.')
            for row in self.db.execute('SELECT m.*,p.dead FROM map_positions m JOIN players p ON p.uid=m.uid WHERE m.on_map=1'):
                if not self.map_passable((row['area'],row['x'],row['y']),bool(row['dead']),data):raise self.error('Новая схема перекрывает персонажа. Переставь его до загрузки.')
            return data
    def map_tick(self):
        if self.meta_value('map_weekly')!='1':return 0
        monday=str(self.clock()-timedelta(days=self.clock().weekday()));epoch='week:'+monday;count=0
        with self.tx():
            for row in self.db.execute('SELECT uid,dead FROM players WHERE approved=1 AND paused=0').fetchall():
                uid=row['uid'];pos=self.map_position(uid)
                if pos['epoch']==epoch or self.char_data(uid)['speed_ft'] is None:continue
                self.map_grant(uid,epoch)
                if not row['dead']:
                    self.db.execute('UPDATE players SET turn=1,extra_used=0,visit=? WHERE uid=?',(str(self.clock()),uid))
                self.notify(uid,'🗓 Новый недельный ход: запас движения обновлён'+('. Ты призрак: доступен только полёт.' if row['dead'] else ', основное действие доступно.'))
                count+=1
        return count
    def map_snapshot(self,uid,area=None):
        viewer=self.map_position(uid);data=self.map_data();area=area or viewer['area']
        if area not in data['floors']:raise self.error('Неизвестный этаж.')
        f=data['floors'][area];tiles=[]
        for y,row in enumerate(f['rows']):
            tiles.append(''.join('?' if not self.map_known(area,x,y,data) else '#' if v=='#' else '.' for x,v in enumerate(row)))
        doors=[]
        for d in data.get('doors',{}).values():
            x,y=coord(d['cell'])
            if d['area']==area and self.map_known(area,x,y,data):doors.append(dict(x=x,y=y,open=d['open']))
        people=[]
        # Allocate unique free arrival cells; guests wait off-map if full.
        for p in self.db.execute('SELECT uid,name,dead FROM players WHERE approved=1'):
            pos=self.map_position(p['uid'])
            if pos['on_map'] and pos['area']==area and self.map_known(area,pos['x'],pos['y'],data):people.append(dict(uid=p['uid'],name=p['name'],dead=bool(p['dead']),x=pos['x'],y=pos['y'],portrait=self.token_get(p['uid'])))
        landmarks=[]
        for key,landmark in data.get('landmarks',{}).items():
            x,y=coord(landmark['cell'])
            if landmark['area']==area and self.map_known(area,x,y,data):landmarks.append(dict(key=key,name=landmark['name'],x=x,y=y))
        npcs=[dict(n) for n in self.db.execute('SELECT * FROM map_npcs WHERE area=?',(area,)) if all(self.map_known(area,xx,yy,data) for yy in range(n['y'],n['y']+n['size']) for xx in range(n['x'],n['x']+n['size']))]
        return dict(npcs=npcs,area=area,name=f['name'],draft=bool(data.get('draft')),tiles=tiles,doors=doors,people=people,landmarks=landmarks,viewer=viewer,uid=uid)
