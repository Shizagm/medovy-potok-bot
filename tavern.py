"""Roy's fictional purse, virtual-gold item shop, separate manual RUB support display."""
import json
from pathlib import Path
import secrets
import time

RARITIES={'common':'Обычный','uncommon':'Необычный','rare':'Редкий','very_rare':'Очень редкий','legendary':'Легендарный'}

class TavernMixin:
    def tavern_schema(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS roy_ledger(id INTEGER PRIMARY KEY,day TEXT NOT NULL,delta INTEGER NOT NULL,actor INTEGER NOT NULL,reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS roy_attempts(rid INTEGER PRIMARY KEY REFERENCES requests(id),uid INTEGER NOT NULL,visit TEXT NOT NULL,result TEXT NOT NULL,UNIQUE(uid,visit));
        CREATE TABLE IF NOT EXISTS shop_catalog(id INTEGER PRIMARY KEY,name TEXT NOT NULL,rarity TEXT NOT NULL,type TEXT NOT NULL,url TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS shop_prices(rarity TEXT PRIMARY KEY,price INTEGER NOT NULL,enabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS shop_orders(id INTEGER PRIMARY KEY,uid INTEGER NOT NULL REFERENCES players(uid),rarity TEXT NOT NULL,price INTEGER NOT NULL,pool TEXT NOT NULL,created INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',item_id INTEGER REFERENCES items(id));
        CREATE TABLE IF NOT EXISTS support_ledger(id INTEGER PRIMARY KEY,day TEXT NOT NULL,amount_rub INTEGER NOT NULL,actor INTEGER NOT NULL,reason TEXT NOT NULL);
        ''')
        cols={x[1] for x in self.db.execute('PRAGMA table_info(items)')}
        for name in ('rarity','source_url','origin'):
            if name not in cols:self.db.execute(f'ALTER TABLE items ADD COLUMN {name} TEXT')
        with self.tx():
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('roy_gold','0')")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('support_enabled','0')")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('support_balance_rub','0')")
            for rarity in RARITIES:
                self.db.execute('INSERT OR IGNORE INTO shop_prices VALUES(?,?,?)',(rarity,400 if rarity=='uncommon' else 0,int(rarity=='uncommon')))
            path=Path(__file__).resolve().parent/'catalog/items.json'
            if path.exists():
                data=json.loads(path.read_text(encoding='utf-8'))
                seen=set()
                for item in data['items']:
                    if type(item['id']) is not int or item['id'] in seen or item['rarity'] not in RARITIES or not item['url'].startswith('https://next.dnd.su/items/'):
                        raise ValueError('Неверная запись каталога')
                    seen.add(item['id'])
                    self.db.execute('INSERT INTO shop_catalog(id,name,rarity,type,url) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,rarity=excluded.rarity,type=excluded.type,url=excluded.url',
                        (item['id'],item['name'],item['rarity'],item['type'],item['url']))

    def meta_value(self,key,default=''):
        row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return row[0] if row else default

    def royal_gold(self):return int(self.meta_value('roy_gold','0'))

    def roy_adjust(self,actor,amount,reason,mode='set'):
        if not reason or mode not in ('set','delta'):raise self.error('Нужны режим и причина.')
        with self.tx():
            old=self.royal_gold();new=amount if mode=='set' else old+amount
            if not 0<=new<=1000000000:raise self.error('Проверь сумму игрового золота Роя.')
            self.db.execute("UPDATE meta SET value=? WHERE key='roy_gold'",(str(new),))
            self.db.execute('INSERT INTO roy_ledger(day,delta,actor,reason) VALUES(?,?,?,?)',(str(self.clock()),new-old,actor,reason))
            return new

    def roy_resolve(self,rid,stealth_mod,hands_mod,perception_mod,dc):
        with self.tx():
            r=self.req(rid)
            if r['kind']!='roy_theft' or r['status']!='pending':raise self.error('Нужна неисполненная попытка обворовать Роя.')
            uid=r['a'];p=self.player(uid)
            if not p['visit']:raise self.error('Мастер ещё не выдал визит.')
            if self.db.execute('SELECT 1 FROM roy_attempts WHERE uid=? AND visit=?',(uid,p['visit'])).fetchone():
                raise self.error('Роя можно попытаться обворовать один раз за визит.')
            balance=self.royal_gold()
            if balance<=0:raise self.error('Кошелёк Роя пуст. Действие не потрачено.')
            self._consume(uid,r['payload']['resource'])
            penalty=self.weakness(uid)
            stealth=None if stealth_mod is None else secrets.randbelow(20)+1+stealth_mod+penalty
            hands=secrets.randbelow(20)+1+hands_mod+penalty
            perception=secrets.randbelow(20)+1+perception_mod
            passive=10+perception_mod
            hidden=stealth is not None and stealth>passive
            detected=not hidden or perception>=stealth
            success=hands>=dc
            amount=min(50,max(1,balance//10)) if success else 0
            result=dict(stealth=stealth,hands=hands,perception=perception,dc=dc,passive=passive,hidden=hidden,penalty=penalty,detected=detected,success=success,amount=amount)
            if amount:
                self.db.execute("UPDATE meta SET value=? WHERE key='roy_gold'",(str(balance-amount),))
                self.db.execute('UPDATE players SET wallet=wallet+? WHERE uid=?',(amount,uid))
                self.log(uid,'roy_theft',amount,f'Кража у Роя · заявка №{rid}',earned=amount)
                self.db.execute('INSERT INTO roy_ledger(day,delta,actor,reason) VALUES(?,?,?,?)',(str(self.clock()),-amount,uid,f'Кража, заявка №{rid}'))
            self.log(uid,'roy_attempt',0,f'Попытка у Роя №{rid}: '+json.dumps(result,ensure_ascii=False))
            self.db.execute('INSERT INTO roy_attempts VALUES(?,?,?,?)',(rid,uid,p['visit'],json.dumps(result)))
            self.db.execute("UPDATE requests SET status='done',rolled=? WHERE id=?",(json.dumps(result),rid))
            self.notify(uid,f'🍯 Попытка обворовать Роя №{rid}\n'+(f'Добыча: {amount} зм.' if success else 'Монеты остались у хозяина.')+'\n'+('Рой узнал тебя.' if detected else 'Рой не узнал, кто это был.'))
            return result

    def shop_pool(self,rarity):
        if rarity not in RARITIES:raise self.error('Неизвестная редкость.')
        return [dict(r) for r in self.db.execute('SELECT * FROM shop_catalog WHERE rarity=? AND enabled=1 ORDER BY id',(rarity,))]

    def shop_price(self,rarity):
        row=self.db.execute('SELECT * FROM shop_prices WHERE rarity=?',(rarity,)).fetchone()
        if not row:raise self.error('Неизвестная редкость.')
        return dict(row)

    def shop_set_price(self,rarity,price):
        if rarity not in RARITIES or not 0<=price<=1000000000:raise self.error('Проверь редкость и цену.')
        with self.tx():self.db.execute('UPDATE shop_prices SET price=?,enabled=? WHERE rarity=?',(price,int(price>0),rarity))

    def shop_toggle(self,cid):
        with self.tx():
            row=self.db.execute('SELECT * FROM shop_catalog WHERE id=?',(cid,)).fetchone()
            if not row:raise self.error('Предмет не найден в каталоге.')
            self.db.execute('UPDATE shop_catalog SET enabled=1-enabled WHERE id=?',(cid,))

    def game_available(self,uid):
        p=self.player(uid);held,_=self._held(uid)
        return max(0,p['wallet']-held)+p['chest']

    def shop_prepare(self,uid,rarity):
        with self.tx():
            p=self.player(uid)
            if p['dead'] or p['paused']:raise self.error('Покупать может живой активный герой.')
            price=self.shop_price(rarity);pool=self.shop_pool(rarity)
            if not price['enabled'] or not pool:raise self.error('Эта полка сейчас закрыта.')
            if self.game_available(uid)<price['price']:raise self.error('Не хватает доступного игрового золота.')
            self.db.execute("UPDATE shop_orders SET status='cancelled' WHERE uid=? AND status='pending'",(uid,))
            cur=self.db.execute('INSERT INTO shop_orders(uid,rarity,price,pool,created) VALUES(?,?,?,?,?)',
                (uid,rarity,price['price'],json.dumps([x['id'] for x in pool]),int(time.time())))
            return dict(id=cur.lastrowid,rarity=rarity,price=price['price'],count=len(pool))

    def shop_order(self,oid):
        row=self.db.execute('SELECT * FROM shop_orders WHERE id=?',(oid,)).fetchone()
        if not row:raise self.error('Заказ не найден.')
        return dict(row)

    def shop_cancel(self,oid,uid):
        with self.tx():
            order=self.shop_order(oid)
            if order['uid']!=uid:raise self.error('Чужой заказ.')
            if order['status']!='pending':raise self.error('Заказ уже закрыт.')
            self.db.execute("UPDATE shop_orders SET status='cancelled' WHERE id=?",(oid,))

    def shop_buy(self,oid,uid):
        with self.tx():
            order=self.shop_order(oid)
            if order['uid']!=uid:raise self.error('Чужой заказ.')
            if order['status']=='done':
                item=dict(self.db.execute('SELECT * FROM items WHERE id=?',(order['item_id'],)).fetchone())
                return dict(order=order,item=item,already=True)
            if order['status']!='pending' or int(time.time())-order['created']>600:raise self.error('Заказ истёк или отменён. Выбери полку заново.')
            p=self.player(uid)
            if p['dead'] or p['paused']:raise self.error('Покупать может живой активный герой.')
            price=self.shop_price(order['rarity']);pool=self.shop_pool(order['rarity'])
            if not price['enabled'] or price['price']!=order['price'] or [x['id'] for x in pool]!=json.loads(order['pool']):
                raise self.error('Цена или состав полки изменились. Подтверди новый заказ.')
            amount=order['price']
            if self.game_available(uid)<amount:raise self.error('Баланс изменился: недостаточно свободного золота.')
            held,_=self._held(uid);wallet=min(max(0,p['wallet']-held),amount);chest=amount-wallet
            picked=pool[secrets.randbelow(len(pool))]
            self.db.execute('UPDATE players SET wallet=wallet-?,chest=chest-? WHERE uid=?',(wallet,chest,uid))
            cur=self.db.execute('INSERT INTO items(owner,name,rarity,source_url,origin) VALUES(?,?,?,?,?)',(uid,picked['name'],picked['rarity'],picked['url'],'roy_shop'))
            iid=cur.lastrowid
            self.db.execute("UPDATE shop_orders SET status='done',item_id=? WHERE id=?",(iid,oid))
            self.log(uid,'shop_buy',-amount,f'Лавка Роя №{oid}: {picked["name"]}, предмет №{iid}',spent=amount)
            item=dict(self.db.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone())
            return dict(order=self.shop_order(oid),item=item,already=False)

    def support_update(self,actor,key,value,reason='Запись мастера'):
        allowed={'support_enabled','support_balance_rub','support_goal','support_report','support_url'}
        if key not in allowed:raise self.error('Неизвестное поле копилки.')
        if key=='support_enabled' and value not in ('0','1'):raise self.error('Значение: 0 или 1.')
        if key=='support_balance_rub':
            try:n=int(value)
            except ValueError:raise self.error('Нужна целая сумма рублей.')
            if not 0<=n<=1000000000:raise self.error('Проверь остаток рублей.')
        if key=='support_url' and value and not value.startswith('https://'):raise self.error('Нужна HTTPS-ссылка или пустое поле.')
        if len(value)>3500:raise self.error('Текст слишком длинный.')
        with self.tx():
            old=int(self.meta_value('support_balance_rub','0'))
            self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,value))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('support_updated',?)",(str(self.clock()),))
            if key=='support_balance_rub':self.db.execute('INSERT INTO support_ledger(day,amount_rub,actor,reason) VALUES(?,?,?,?)',(str(self.clock()),int(value)-old,actor,reason))
