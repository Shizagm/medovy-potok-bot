"""Private character records, paid snapshots and resurrection house rules."""
from datetime import date,timedelta
import json
import time

class CharactersMixin:
    def characters_schema(self):
        cols={r[1] for r in self.db.execute('PRAGMA table_info(players)')}
        if 'resurrected_on' not in cols:self.db.execute('ALTER TABLE players ADD COLUMN resurrected_on TEXT')
        if 'death_seq' not in cols:self.db.execute('ALTER TABLE players ADD COLUMN death_seq INTEGER NOT NULL DEFAULT 0')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS character_stats(
          uid INTEGER PRIMARY KEY REFERENCES players(uid),ac INTEGER,hp_now INTEGER,hp_max INTEGER,
          speed_ft INTEGER,passive INTEGER,weapons TEXT,bag TEXT,version INTEGER NOT NULL DEFAULT 0,updated TEXT);
        CREATE TABLE IF NOT EXISTS info_orders(
          id INTEGER PRIMARY KEY,buyer INTEGER NOT NULL REFERENCES players(uid),target INTEGER NOT NULL REFERENCES players(uid),
          created INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',snapshot TEXT);
        CREATE TABLE IF NOT EXISTS res_orders(
          id INTEGER PRIMARY KEY,sponsor INTEGER NOT NULL REFERENCES players(uid),target INTEGER NOT NULL REFERENCES players(uid),
          death_seq INTEGER NOT NULL,created INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending');
        ''')
        # Avoid delivering obsolete public item details after private-card migration.
        if not self.db.execute("SELECT 1 FROM meta WHERE key='private_cards_v7'").fetchone():
            with self.tx():
                self.db.execute("UPDATE outbox SET text=? WHERE sent=0 AND target<0 AND text LIKE '🎁 НАХОДКА ИЗ ЛАВКИ РОЯ%'",('🎁 Рой передал герою находку. Подробности хранятся в закрытой карточке.',))
                self.db.execute("INSERT INTO meta VALUES('private_cards_v7','1')")

    def require_alive(self,uid):
        p=self.player(uid)
        if p['dead']:raise self.error('Ты призрак: доступны полёт, общение, просмотр своего профиля и выкуп себя у Шизы.')
        if p['paused']:raise self.error('Участие приостановлено мастером.')
        return p

    def weakness(self,uid):
        p=self.player(uid)
        value=p.get('resurrected_on')
        if not value:return 0
        weeks=max(0,(self.clock()-date.fromisoformat(value)).days)//7
        return -max(0,4-weeks)

    def weakness_next(self,uid):
        p=self.player(uid);value=p.get('resurrected_on')
        if not value or not self.weakness(uid):return None
        elapsed=max(0,(self.clock()-date.fromisoformat(value)).days)//7
        return str(date.fromisoformat(value)+timedelta(days=7*(elapsed+1)))

    def char_data(self,uid):
        self.player(uid)
        self.db.execute('INSERT OR IGNORE INTO character_stats(uid) VALUES(?)',(uid,))
        return dict(self.db.execute('SELECT * FROM character_stats WHERE uid=?',(uid,)).fetchone())

    def validate_stats(self,data):
        out={}
        for key,lo,hi in (('ac',0,100),('hp_now',0,1000000),('hp_max',1,1000000),('speed_ft',0,1000),('passive',0,100)):
            value=data.get(key)
            if type(value) is not int or not lo<=value<=hi:raise self.error('Проверь поле '+key)
            out[key]=value
        if out['hp_now']>out['hp_max']:raise self.error('Текущие хиты не могут превышать максимум.')
        for key in ('weapons','bag'):
            value=data.get(key)
            if not isinstance(value,str) or not 1<=len(value)<=1200:raise self.error('Оружие и багаж: до 1200 символов, «нет» если пусто.')
            out[key]=value
        return out

    def char_request(self,uid,data,editor=None):
        clean=self.validate_stats(data)
        with self.tx():
            if editor is None:self.require_alive(uid)
            else:self.player(uid)
            clean['editor']=editor
            cur=self.db.execute("INSERT INTO requests(kind,a,payload,created) VALUES('character_update',?,?,?)",(uid,json.dumps(clean,ensure_ascii=False),str(self.clock())))
            return cur.lastrowid

    def apply_stats(self,uid,data,exclude_request=None):
        clean=self.validate_stats(data);p=self.player(uid)
        if p['dead'] and clean['hp_now']>0:raise self.error('Изменение карточки не воскрешает: у призрака хиты должны быть 0.')
        with self.tx():
            self.db.execute('INSERT OR IGNORE INTO character_stats(uid) VALUES(?)',(uid,))
            self.db.execute('UPDATE character_stats SET ac=?,hp_now=?,hp_max=?,speed_ft=?,passive=?,weapons=?,bag=?,version=version+1,updated=? WHERE uid=?',
                (clean['ac'],clean['hp_now'],clean['hp_max'],clean['speed_ft'],clean['passive'],clean['weapons'],clean['bag'],str(self.clock()),uid))
            if clean['hp_now']==0 and not p['dead']:self.life(uid,True,exclude_request=exclude_request)
            self.log(uid,'character_update',0,'Карточка подтверждена мастером')

    def set_hp(self,uid,hp):
        with self.tx():
            p=self.player(uid);c=self.char_data(uid)
            if type(hp) is not int or c['hp_max'] is None or not 0<=hp<=c['hp_max']:raise self.error('Укажи хиты от 0 до максимума подтверждённой карточки.')
            if p['dead'] and hp>0:raise self.error('Для возвращения к жизни нужен выкуп у Шизы.')
            self.db.execute('UPDATE character_stats SET hp_now=?,updated=?,version=version+1 WHERE uid=?',(hp,str(self.clock()),uid))
            if hp==0 and not p['dead']:self.life(uid,True)
            self.log(uid,'health',0,f'Хиты: {hp}/{c["hp_max"]}')

    def char_snapshot(self,uid):
        p=self.player(uid);c=self.char_data(uid)
        items=[dict(r) for r in self.db.execute('SELECT name,rarity,source_url FROM items WHERE owner=? ORDER BY id',(uid,))]
        return dict(name=p['name'],ac=c['ac'],hp_now=0 if p['dead'] else c['hp_now'],hp_max=c['hp_max'],speed_ft=c['speed_ft'],passive=c['passive'],weapons=c['weapons'],bag=c['bag'],items=items,dead=bool(p['dead']),penalty=self.weakness(uid),next_recovery=self.weakness_next(uid),updated=c['updated'],snapshot_day=str(self.clock()))

    def card_ready(self,uid):
        c=self.char_data(uid)
        return all(c[k] is not None for k in ('ac','hp_now','hp_max','speed_ft','passive','weapons','bag'))

    def debit_character_gold(self,uid,amount,kind,reason,spent=True):
        p=self.player(uid);held,_=self._held(uid)
        available=max(0,p['wallet']-held)+p['chest']
        if amount>available:raise self.error(f'Нужно {amount} свободных зм в кошельке и сундуке.')
        wallet=min(max(0,p['wallet']-held),amount);chest=amount-wallet
        self.db.execute('UPDATE players SET wallet=wallet-?,chest=chest-? WHERE uid=?',(wallet,chest,uid))
        self.log(uid,kind,-amount,reason,spent=amount if spent else 0)

    def info_prepare(self,buyer,target):
        with self.tx():
            self.require_alive(buyer);self.player(target)
            if buyer==target:raise self.error('Своя карточка доступна бесплатно.')
            if not self.card_ready(target):raise self.error('Мастер ещё не заполнил карточку этого героя.')
            if self.game_available(buyer)<500:raise self.error('Для сведений Роя нужно 500 зм.')
            self.db.execute("UPDATE info_orders SET status='cancelled' WHERE buyer=? AND status='pending'",(buyer,))
            cur=self.db.execute('INSERT INTO info_orders(buyer,target,created) VALUES(?,?,?)',(buyer,target,int(time.time())))
            return cur.lastrowid

    def info_pay(self,oid,buyer):
        with self.tx():
            row=self.db.execute('SELECT * FROM info_orders WHERE id=?',(oid,)).fetchone()
            if not row or row['buyer']!=buyer:raise self.error('Чужая справка.')
            if row['status']=='done':return json.loads(row['snapshot']),True
            self.require_alive(buyer)
            if row['status']!='pending' or int(time.time())-row['created']>600:raise self.error('Предложение истекло. Выбери героя заново.')
            if not self.card_ready(row['target']):raise self.error('Карточка пока не готова.')
            snap=self.char_snapshot(row['target'])
            self.debit_character_gold(buyer,500,'info_purchase',f'Сведения Роя о {snap["name"]}')
            self.db.execute("UPDATE info_orders SET status='done',snapshot=? WHERE id=?",(json.dumps(snap,ensure_ascii=False),oid))
            return snap,False

    def info_saved(self,oid,buyer):
        row=self.db.execute("SELECT snapshot FROM info_orders WHERE id=? AND buyer=? AND status='done'",(oid,buyer)).fetchone()
        if not row:raise self.error('Эта справка тебе не принадлежит.')
        return json.loads(row['snapshot'])

    def res_prepare(self,sponsor,target):
        with self.tx():
            payer=self.player(sponsor);p=self.player(target)
            if sponsor!=target:self.require_alive(sponsor)
            elif payer['paused']:raise self.error('Участие приостановлено мастером.')
            if not p['dead']:raise self.error('Этот герой уже жив.')
            if p['paused']:raise self.error('Участие героя приостановлено мастером.')
            if self.char_data(target)['hp_max'] is None:raise self.error('Мастер должен указать максимум здоровья героя до воскрешения.')
            if self.game_available(sponsor)<1000:raise self.error('Для выкупа у Шизы нужно 1000 свободных зм.')
            self.db.execute("UPDATE res_orders SET status='cancelled' WHERE sponsor=? AND status='pending'",(sponsor,))
            cur=self.db.execute('INSERT INTO res_orders(sponsor,target,death_seq,created) VALUES(?,?,?,?)',(sponsor,target,p['death_seq'],int(time.time())))
            return cur.lastrowid

    def res_pay(self,oid,sponsor):
        with self.tx():
            row=self.db.execute('SELECT * FROM res_orders WHERE id=?',(oid,)).fetchone()
            if not row or row['sponsor']!=sponsor:raise self.error('Чужой выкуп.')
            if row['status']=='done':return row['target'],True
            if row['status']!='pending' or int(time.time())-row['created']>600:raise self.error('Выкуп истёк или отменён.')
            target=row['target'];p=self.player(target)
            if not p['dead'] or p['death_seq']!=row['death_seq']:raise self.error('Это предложение относится к прошлой смерти или герой уже жив.')
            if p['paused']:raise self.error('Участие героя приостановлено мастером.')
            payer=self.player(sponsor)
            if sponsor!=target:self.require_alive(sponsor)
            elif payer['paused']:raise self.error('Участие приостановлено мастером.')
            maximum=self.char_data(target)['hp_max']
            if maximum is None:raise self.error('Не указан максимум здоровья.')
            self._settle(target,self.clock())
            self.debit_character_gold(sponsor,1000,'resurrection',f'Выкуп {p["name"]} у Шизы')
            self.db.execute('UPDATE players SET dead=0,resurrected_on=? WHERE uid=?',(str(self.clock()),target))
            self.db.execute('UPDATE character_stats SET hp_now=hp_max,version=version+1,updated=? WHERE uid=?',(str(self.clock()),target))
            self.db.execute("UPDATE res_orders SET status='done' WHERE id=?",(oid,))
            self.db.execute("UPDATE res_orders SET status='cancelled' WHERE target=? AND id!=? AND status='pending'",(target,oid))
            self.log(target,'resurrected',0,f'Шиза вернул к жизни. Штраф -4; оплатил {sponsor}')
            self.notify(target,'🕯 Шиза вернул тебя к жизни. Переверни жетон лицевой стороной. Здоровье восстановлено, штраф к проверкам −4. Через 7 дней станет −3.')
            return target,False

    def on_character_death(self,uid,exclude_request=None):
        self.db.execute('INSERT OR IGNORE INTO character_stats(uid) VALUES(?)',(uid,))
        self.db.execute('UPDATE character_stats SET hp_now=0,version=version+1,updated=? WHERE uid=?',(str(self.clock()),uid))
        self.db.execute('UPDATE players SET turn=0,death_seq=death_seq+1 WHERE uid=?',(uid,))
        for row in self.db.execute("SELECT id FROM poker WHERE status IN ('active','showdown') AND (a=? OR b=?)",(uid,uid)).fetchall():self._poker_cancel(row['id'],'персонаж стал призраком; ставки возвращены')
        self.db.execute("UPDATE requests SET status='cancelled' WHERE a=? AND id!=? AND (status='pending' OR (kind='action' AND status='done' AND rolled IS NULL))",(uid,exclude_request or -1))
        self.db.execute("UPDATE shop_orders SET status='cancelled' WHERE uid=? AND status='pending'",(uid,))
        self.db.execute("UPDATE info_orders SET status='cancelled' WHERE buyer=? AND status='pending'",(uid,))
        self.db.execute("UPDATE res_orders SET status='cancelled' WHERE sponsor=? AND target!=? AND status='pending'",(uid,uid))
        self.notify(uid,'🕯 Ты стал призраком. Переверни жетон обратной стороной. Можно летать и общаться; действия и сделки закрыты. Выкуп у Шизы — 1000 зм: оплатить можешь ты или живой герой.')
