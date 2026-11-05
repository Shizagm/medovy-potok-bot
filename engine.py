"""Transactional rules for Medovy Potok. No Telegram dependencies."""
import contextlib
import json
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    TZ = ZoneInfo('Asia/Yekaterinburg')
except ZoneInfoNotFoundError:
    # Windows may lack the IANA database. Tavern dates use current UTC+05:00.
    TZ = timezone(timedelta(hours=5), name='Yekaterinburg')
ROOMS = {0: ('Общий зал', 0, 0), 1: ('Койка', 20, 1000),
         2: ('Комната', 50, 5000), 3: ('Большая комната', 100, 10000)}

class RuleError(Exception):
    pass

from games import GamesMixin

from tavern import TavernMixin

from characters import CharactersMixin

from map_rules import MapMixin

from token_rules import TokensMixin

class Engine(GamesMixin,TavernMixin,CharactersMixin,MapMixin,TokensMixin):
    error = RuleError
    def __init__(self, path='data/tavern.sqlite3', clock=None):
        self.clock = clock or (lambda: datetime.now(TZ).date())
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS players(
          uid INTEGER PRIMARY KEY, name TEXT NOT NULL, party TEXT NOT NULL,
          approved INTEGER NOT NULL DEFAULT 0,
          wallet INTEGER NOT NULL DEFAULT 0 CHECK(wallet>=0),
          chest INTEGER NOT NULL DEFAULT 0 CHECK(chest>=0),
          custody INTEGER NOT NULL DEFAULT 0 CHECK(custody>=0),
          inspiration INTEGER NOT NULL DEFAULT 0 CHECK(inspiration IN (0,1)),
          turn INTEGER NOT NULL DEFAULT 0 CHECK(turn IN (0,1)),
          extra_used INTEGER NOT NULL DEFAULT 0,
          visit TEXT, tier INTEGER NOT NULL DEFAULT 0,
          dead INTEGER NOT NULL DEFAULT 0, paused INTEGER NOT NULL DEFAULT 0, settled TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS items(
          id INTEGER PRIMARY KEY, owner INTEGER NOT NULL REFERENCES players(uid),
          name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests(
          id INTEGER PRIMARY KEY, kind TEXT NOT NULL, a INTEGER NOT NULL,
          b INTEGER, payload TEXT NOT NULL, ca INTEGER NOT NULL DEFAULT 0,
          cb INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
          rolled TEXT, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ledger(
          id INTEGER PRIMARY KEY, uid INTEGER NOT NULL REFERENCES players(uid),
          day TEXT NOT NULL, kind TEXT NOT NULL, delta INTEGER NOT NULL,
          earned INTEGER NOT NULL DEFAULT 0, spent INTEGER NOT NULL DEFAULT 0,
          reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox(
          id INTEGER PRIMARY KEY, target INTEGER NOT NULL, text TEXT NOT NULL,
          sent INTEGER NOT NULL DEFAULT 0);
        ''')
        self.games_schema()
        self.tavern_schema()
        if 'paused' not in [r[1] for r in self.db.execute('PRAGMA table_info(players)')]:
            self.db.execute('ALTER TABLE players ADD COLUMN paused INTEGER NOT NULL DEFAULT 0')
        self.characters_schema()
        self.map_schema()

    @contextlib.contextmanager
    def tx(self):
        if self.db.in_transaction:
            yield
            return
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def player(self, uid, approved=True):
        p = self.db.execute('SELECT * FROM players WHERE uid=?', (uid,)).fetchone()
        if p is None or (approved and not p['approved']):
            raise RuleError('Персонаж не зарегистрирован или ещё не одобрен мастером.')
        return dict(p)

    def notify(self, uid, text):
        self.db.execute('INSERT INTO outbox(target,text) VALUES(?,?)', (uid,text))

    def log(self, uid, kind, delta, reason, earned=0, spent=0, day=None):
        self.db.execute('INSERT INTO ledger(uid,day,kind,delta,earned,spent,reason) '
                        'VALUES(?,?,?,?,?,?,?)',
                        (uid, str(day or self.clock()), kind, delta, earned, spent, reason))

    def register(self, uid, name, party):
        if not 1 <= len(name) <= 60 or not 1 <= len(party) <= 60:
            raise RuleError('Имя и отряд: от 1 до 60 символов.')
        with self.tx():
            if self.db.execute('SELECT 1 FROM players WHERE uid=?',(uid,)).fetchone():
                raise RuleError('Профиль уже существует. Изменения — через мастера.')
            self.db.execute('INSERT INTO players(uid,name,party,settled) VALUES(?,?,?,?)',
                            (uid,name,party,str(self.clock())))

    def approve(self, uid):
        with self.tx():
            self.player(uid, False)
            self.db.execute('UPDATE players SET approved=1,settled=? WHERE uid=?',
                            (str(self.clock()),uid))
            self.notify(uid,'Рой записал тебя в книгу гостей. Открой /profile.')

    def ledger_for(self, uid, limit=15):
        return [dict(x) for x in self.db.execute(
            'SELECT * FROM ledger WHERE uid=? ORDER BY id DESC LIMIT ?', (uid,limit))]

    def _held(self, uid, exclude=0):
        gold = self._poker_held(uid)
        items = set()
        for r in self.db.execute("SELECT * FROM requests WHERE kind='trade' AND status='pending' AND id!=? AND (a=? OR b=?) AND ca=1 AND cb=1",(exclude,uid,uid)):
            p=json.loads(r['payload']); side='give' if r['a']==uid else 'take'
            gold += p[side+'_gold']; items.update(p[side+'_items'])
        return gold,items

    def _cancel_trades(self, uid, reason):
        self._cancel_poker_for_user(uid,reason)
        for r in self.db.execute("SELECT id,a,b FROM requests WHERE kind='trade' AND status='pending' AND (a=? OR b=?)",(uid,uid)).fetchall():
            self.db.execute("UPDATE requests SET status='cancelled' WHERE id=?",(r['id'],))
            for who in (r['a'],r['b']):
                self.notify(who,f"Сделка №{r['id']} отменена: {reason}")

    def adjust(self, uid, amount, reason, mode='delta', earned=False, spent=False):
        if not reason or mode not in ('delta','set'):
            raise RuleError('Нужны режим delta/set и причина.')
        with self.tx():
            p=self.player(uid)
            delta=amount-p['wallet'] if mode=='set' else amount
            if p['wallet']+delta < 0:
                raise RuleError('Недостаточно золота в кошельке.')
            self._cancel_trades(uid,'мастер изменил баланс; подтвердите условия заново')
            self.db.execute('UPDATE players SET wallet=wallet+? WHERE uid=?',(delta,uid))
            self.log(uid,'correction' if mode=='set' else 'money',delta,reason,
                     max(delta,0) if earned else 0,max(-delta,0) if spent else 0)

    def rank_adjust(self, uid, earned, spent, reason):
        with self.tx():
            self.player(uid)
            self.log(uid,'ranking_correction',0,reason,earned,spent)

    def inspiration(self, uid, value):
        if value not in (0,1): raise RuleError('Вдохновение: 0 или 1.')
        with self.tx():
            p=self.player(uid)
            if value==1 and p['inspiration']:
                raise RuleError('Вдохновение уже есть. Новое не накапливается.')
            self.db.execute('UPDATE players SET inspiration=? WHERE uid=?',(value,uid))
            self.log(uid,'inspiration',0,f'Вдохновение Роя: {value}')
            self.notify(uid,'Вдохновение Роя выдано.' if value else 'Вдохновение Роя снято.')

    def visit(self, uid):
        with self.tx():
            if self.meta_value('map_weekly')=='1':raise RuleError('Включён недельный режим: ход выдаётся автоматически. /mapgrant обновляет только передвижение.')
            p=self.player(uid)
            if p['visit']==str(self.clock()): raise RuleError('Ход за сегодняшний визит уже выдан.')
            self.db.execute('UPDATE players SET visit=?,turn=1,extra_used=0 WHERE uid=?',
                            (str(self.clock()),uid))
            if not p['paused'] and self.char_data(uid)['speed_ft'] is not None:self.map_grant(uid,'visit:'+str(self.clock()))
            self.notify(uid,'Новый визит: одно основное действие. Старое не накапливается.')

    def action_available(self,uid,resource):
        p=self.require_alive(uid)
        if resource=='base':
            if not p['turn']:raise RuleError('Основное действие сейчас недоступно.')
        elif resource=='inspiration':
            if not p['inspiration'] or p['extra_used'] or not p['visit'] or p['turn']:raise RuleError('Дополнительное действие недоступно: нужно Вдохновение и уже потраченный основной ход.')
        else:raise RuleError('Неизвестный ресурс действия.')

    def request(self, uid, kind, payload):
        if kind not in ('action','rent','storage','spend','roy_theft'): raise RuleError('Неизвестная заявка.')
        with self.tx():
            self.require_alive(uid)
            if self.db.execute("SELECT count(*) FROM requests WHERE a=? AND status='pending'",(uid,)).fetchone()[0]>=10:
                raise RuleError('Сначала заверши предыдущие заявки (максимум 10).')
            c=self.db.execute('INSERT INTO requests(kind,a,payload,created) VALUES(?,?,?,?)',
                              (kind,uid,json.dumps(payload,ensure_ascii=False),str(self.clock())))
            return c.lastrowid

    def req(self, rid):
        r=self.db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
        if not r: raise RuleError('Заявка не найдена.')
        r=dict(r); r['payload']=json.loads(r['payload']); return r

    def trade(self, a, b, give_gold, take_gold, give_items, take_items, note):
        if a==b or min(give_gold,take_gold)<0: raise RuleError('Неверные стороны или суммы.')
        if not (give_gold or take_gold or give_items or take_items): raise RuleError('Пустая сделка.')
        if len(set(give_items+take_items))!=len(give_items+take_items): raise RuleError('Предмет указан дважды.')
        with self.tx():
            self.player(a); self.player(b)
            if self.db.execute("SELECT count(*) FROM requests WHERE kind='trade' AND status='pending' AND (a=? OR b=?)",(a,a)).fetchone()[0]>=10:
                raise RuleError('Слишком много незавершённых сделок.')
            p=dict(give_gold=give_gold,take_gold=take_gold,give_items=give_items,take_items=take_items,note=note[:500])
            c=self.db.execute("INSERT INTO requests(kind,a,b,payload,created) VALUES('trade',?,?,?,?)",(a,b,json.dumps(p,ensure_ascii=False),str(self.clock())))
            self._validate_trade(a,b,p)
            return c.lastrowid

    def _validate_trade(self, a, b, p, exclude=0):
        self.map_trade_check(a,b)
        for uid,side in ((a,'give'),(b,'take')):
            pl=self.player(uid)
            if pl['dead'] or pl['paused']: raise RuleError('Призраки и персонажи на паузе не торгуют.')
            held,items=self._held(uid,exclude)
            if p[side+'_gold']>pl['wallet']-held: raise RuleError('Недостаточно свободного золота в кошельке.')
            for iid in p[side+'_items']:
                item=self.db.execute('SELECT owner FROM items WHERE id=?',(iid,)).fetchone()
                if not item or item['owner']!=uid or iid in items: raise RuleError('Предмет отсутствует или зарезервирован.')

    def confirm(self, rid, uid):
        with self.tx():
            r=self.req(rid)
            if r['status']!='pending' or r['kind']!='trade': raise RuleError('Сделка уже закрыта.')
            if uid not in (r['a'],r['b']): raise RuleError('Ты не участник этой сделки.')
            self._validate_trade(r['a'],r['b'],r['payload'],rid)
            col='ca' if uid==r['a'] else 'cb'
            self.db.execute(f'UPDATE requests SET {col}=1 WHERE id=?',(rid,))
            return self.req(rid)

    def cancel(self, rid, uid, admin=False):
        with self.tx():
            r=self.req(rid)
            if r['status']!='pending': raise RuleError('Заявка уже закрыта.')
            if not admin and uid not in (r['a'],r['b']): raise RuleError('Чужая заявка.')
            self.db.execute("UPDATE requests SET status='cancelled' WHERE id=?",(rid,))
            for who in set(x for x in (r['a'],r['b']) if x): self.notify(who,f'Заявка №{rid} отменена.')

    def _consume(self, uid, resource, ghost_ok=False):
        p=self.player(uid)
        if p['paused']: raise RuleError('Участие приостановлено мастером.')
        if p['dead'] and not ghost_ok: raise RuleError('Сначала нужно вернуться с кладбища.')
        if resource=='base':
            if not p['turn']: raise RuleError('Нет основного действия. Мастер выдаёт его командой /visit.')
            self.db.execute('UPDATE players SET turn=0 WHERE uid=?',(uid,))
        elif resource=='inspiration':
            if not p['inspiration'] or p['extra_used'] or not p['visit'] or p['turn']:
                raise RuleError('Нет Вдохновения или дополнительное действие за визит уже использовано.')
            self.db.execute('UPDATE players SET inspiration=0,extra_used=1 WHERE uid=?',(uid,))
        else: raise RuleError('Ресурс: base или inspiration.')

    def approve_request(self, rid):
        with self.tx():
            r=self.req(rid); p=r['payload']; uid=r['a']
            if r['status']!='pending': raise RuleError('Заявка уже закрыта.')
            if r['kind']=='roy_theft':raise RuleError('Для попытки у Роя назначь проверки через кнопку заявки или /royrob.')
            pl=self.player(uid)
            if r['kind']!='character_update':self.require_alive(uid)
            if r['kind']=='character_update':
                self.apply_stats(uid,p,exclude_request=rid)
            elif r['kind']=='trade':
                if not (r['ca'] and r['cb']): raise RuleError('Нужны подтверждения обоих игроков.')
                self._validate_trade(uid,r['b'],p,rid)
                for who,side,other in ((uid,'give',r['b']),(r['b'],'take',uid)):
                    amount=p[side+'_gold']
                    self.db.execute('UPDATE players SET wallet=wallet-? WHERE uid=?',(amount,who))
                    self.db.execute('UPDATE players SET wallet=wallet+? WHERE uid=?',(amount,other))
                    self.log(who,'trade_out',-amount,f'Сделка №{rid}',spent=amount)
                    self.log(other,'trade_in',amount,f'Сделка №{rid}')
                    for iid in p[side+'_items']:
                        self.db.execute('UPDATE items SET owner=? WHERE id=?',(other,iid))
            elif r['kind']=='action':
                self._consume(uid,p['resource'])
                self.log(uid,'action',0,f"Заявка №{rid}: {p['text']}")
            elif r['kind']=='rent':
                tier=p['tier']
                if tier not in ROOMS: raise RuleError('Нет такого жилья.')
                self._settle(uid,self.clock())
                pl=self.player(uid)
                if pl['chest']>ROOMS[tier][2]: raise RuleError('Сначала освободи сундук до нового лимита.')
                self.db.execute('UPDATE players SET tier=? WHERE uid=?',(tier,uid))
                self.log(uid,'rent_change',0,f'Жильё: {ROOMS[tier][0]}')
            elif r['kind']=='storage':
                amount=p['amount']; direction=p['direction']
                if amount<=0: raise RuleError('Сумма должна быть положительной.')
                held,_=self._held(uid)
                if direction=='in':
                    if pl['tier']==0 or pl['wallet']-held<amount or pl['chest']+amount>ROOMS[pl['tier']][2]:
                        raise RuleError('Нет места в сундуке или свободных монет.')
                    self.db.execute('UPDATE players SET wallet=wallet-?,chest=chest+? WHERE uid=?',(amount,amount,uid))
                elif direction=='out':
                    if pl['chest']<amount: raise RuleError('В сундуке недостаточно монет.')
                    self.db.execute('UPDATE players SET wallet=wallet+?,chest=chest-? WHERE uid=?',(amount,amount,uid))
                else: raise RuleError('Направление: in/out.')
            elif r['kind']=='spend':
                amount=p['amount']; held,_=self._held(uid)
                if amount<=0 or amount>pl['wallet']-held: raise RuleError('Недостаточно свободного золота.')
                self.db.execute('UPDATE players SET wallet=wallet-? WHERE uid=?',(amount,uid))
                self.log(uid,'spend',-amount,p['text'],spent=amount)
            self.db.execute("UPDATE requests SET status='done' WHERE id=?",(rid,))
            for who in set(x for x in (uid,r['b']) if x): self.notify(who,f'Заявка №{rid} исполнена мастером.')
            return r

    def check(self, rid, modifier, dc, die=None):
        with self.tx():
            r=self.req(rid)
            if r['kind']!='action' or r['status']!='done' or r['rolled']:
                raise RuleError('Нет разрешённой непроверенной заявки.')
            self.require_alive(r['a'])
            base_modifier=modifier;penalty=self.weakness(r['a']);modifier+=penalty
            source='bot' if die is None else 'table'
            die=secrets.randbelow(20)+1 if die is None else die
            if type(die) is not int or not 1<=die<=20: raise RuleError('Результат d20 должен быть от 1 до 20.')
            result=dict(die=die,modifier=modifier,total=die+modifier,dc=dc,success=die+modifier>=dc,source=source,base_modifier=base_modifier,penalty=penalty)
            self.db.execute('UPDATE requests SET rolled=? WHERE id=?',(json.dumps(result),rid))
            return result

    def add_item(self, uid, name):
        with self.tx():
            self.player(uid)
            c=self.db.execute('INSERT INTO items(owner,name) VALUES(?,?)',(uid,name[:120]))
            return c.lastrowid

    def life(self, uid, dead, exclude_request=None):
        with self.tx():
            p=self.player(uid)
            if not dead:
                if p['dead']:raise RuleError('Возвращение к жизни — выкуп у Шизы за 1000 зм. Открой /resurrect.')
                return
            if p['dead']:return
            self._settle(uid,self.clock())
            self._cancel_trades(uid,'персонаж стал призраком')
            self.db.execute('UPDATE players SET dead=1 WHERE uid=?',(uid,))
            self.on_character_death(uid,exclude_request)
            self.log(uid,'life',0,'Призрак: только полёт, общение и выкуп себя')

    def revive(self, actor, target):
        raise RuleError('Бесплатное возвращение отменено. Используй /resurrect и подтверди выкуп у Шизы за 1000 зм.')

    def rob(self, thief, victim, amount, source, stealth_mod, hands_mod, perception_mod, dc):
        if thief==victim or source not in ('wallet','chest') or amount<=0:
            raise RuleError('Неверные условия кражи.')
        with self.tx():
            self.require_alive(thief); v=self.player(victim)
            if source=='wallet':self.map_trade_check(thief,victim)
            passive=self.char_data(victim)['passive']
            if passive is None:raise RuleError('Мастер должен заполнить пассивное Восприятие жертвы.')
            if v['dead'] or v['paused']: raise RuleError('Кражи у призраков и персонажей на паузе не разрешены.')
            if self.db.execute("SELECT 1 FROM ledger WHERE uid=? AND kind='robbed' AND day>?",(victim,str(self.clock()-timedelta(days=30)))).fetchone():
                raise RuleError('У жертвы действует защита от повторного ограбления (30 дней).')
            cap=min(v[source]//10,50) if source=='wallet' else v[source]//5
            if amount>cap: raise RuleError(f'Лимит добычи: {cap} зм.')
            self._consume(thief,'base')
            thief_penalty=self.weakness(thief);victim_penalty=self.weakness(victim)
            stealth=None if stealth_mod is None else secrets.randbelow(20)+1+stealth_mod+thief_penalty
            hands=secrets.randbelow(20)+1+hands_mod+thief_penalty
            perception=secrets.randbelow(20)+1+perception_mod+victim_penalty
            hidden=stealth is not None and stealth>passive
            detected=not hidden or perception>=stealth
            success=hands>=dc
            if success:
                self._cancel_trades(victim,'изменился доступный баланс')
                self.db.execute(f'UPDATE players SET {source}={source}-? WHERE uid=?',(amount,victim))
                self.db.execute('UPDATE players SET wallet=wallet+? WHERE uid=?',(amount,thief))
                self.log(victim,'robbed',-amount,'Кража: сведения у мастера')
                self.log(thief,'theft',amount,f'Ограбление персонажа {victim}',earned=amount)
            self.log(thief,'theft_attempt',0,json.dumps(dict(victim=victim,stealth=stealth,hands=hands,perception=perception,dc=dc,passive=passive,hidden=hidden,thief_penalty=thief_penalty,victim_penalty=victim_penalty,success=success,detected=detected)))
            self.notify(victim,(f'Ты замечаешь вора: {self.player(thief)["name"]}. ' if detected else 'Личность вора неизвестна. ')+('Пропало золото; проверь баланс.' if success else 'Добычи у вора нет.') if detected or success else 'Проверка обстановки завершена. Подробности у мастера.')
            return dict(stealth=stealth,hands=hands,perception=perception,passive=passive,hidden=hidden,thief_penalty=thief_penalty,victim_penalty=victim_penalty,success=success,detected=detected)

    def _settle(self, uid, until):
        p=self.player(uid); start=date.fromisoformat(p['settled'])
        if start>=until: return
        if p['paused']:
            self.db.execute('UPDATE players SET settled=? WHERE uid=?',(str(until),uid))
            return
        self._cancel_trades(uid,'проводится расчёт постоя; подтвердите условия заново')
        wallet,chest,custody,tier=p['wallet'],p['chest'],p['custody'],p['tier']
        def pay(n):
            nonlocal wallet,chest
            w=min(wallet,n); wallet-=w; chest-=n-w
        for i in range((until-start).days):
            day=start+timedelta(days=i)
            food=min(0 if p['dead'] else 1,wallet+chest)
            pay(food)
            rent=ROOMS[tier][1]
            if wallet+chest<rent:
                custody+=chest; chest=0; tier=0; rent=0
                self.notify(uid,'Рой освободил жильё из-за нехватки средств. Остаток сундука хранится у Роя.')
            pay(rent)
            if food or rent:
                self.log(uid,'lodging',-(food+rent),f'Питание {food}; аренда {rent}',spent=food+rent,day=day)
        self.db.execute('UPDATE players SET wallet=?,chest=?,custody=?,tier=?,settled=? WHERE uid=?',(wallet,chest,custody,tier,str(until),uid))
        self.notify(uid,f'Расчёт до {until}: списано {p["wallet"]+p["chest"]+p["custody"]-wallet-chest-custody} зм. Кошелёк {wallet}, сундук {chest}, у Роя {custody}.')

    def settle(self, until=None):
        until=until or self.clock()
        if until>self.clock(): raise RuleError('Нельзя списывать за будущее.')
        with self.tx():
            for row in self.db.execute('SELECT uid FROM players WHERE approved=1').fetchall():
                self._settle(row['uid'],until)

    def weekly(self):
        today=self.clock(); monday=today-timedelta(days=today.weekday())
        self.settle(monday)
        return monday

    def pause(self, uid, value):
        if value not in (0,1): raise RuleError('Пауза: 0 или 1.')
        with self.tx():
            self.player(uid); self._settle(uid,self.clock())
            self._cancel_trades(uid,'изменился статус участия')
            self.db.execute('UPDATE players SET paused=?,settled=? WHERE uid=?',(value,str(self.clock()),uid))
            self.db.execute('UPDATE map_positions SET rev=rev+1 WHERE uid=?',(uid,))
            self.log(uid,'pause',0,f'Пауза: {value}')

    def reclaim(self, uid):
        with self.tx():
            p=self.player(uid)
            self.db.execute('UPDATE players SET wallet=wallet+custody,custody=0 WHERE uid=?',(uid,))
            self.log(uid,'custody_return',0,f'Рой вернул {p["custody"]} зм')

    def rankings(self, month=None):
        month=month or str(self.clock())[:7]
        rich=[(r['name'],r['total']) for r in self.db.execute("SELECT p.name,p.wallet+p.chest+p.custody+COALESCE((SELECT SUM(g.stake) FROM poker g WHERE g.status IN ('active','showdown') AND (g.a=p.uid OR g.b=p.uid)),0) AS total FROM players p WHERE p.approved=1 ORDER BY total DESC,p.uid LIMIT 30")]
        out={'Самые богатые':rich}
        for col,label in (('earned','Заработок месяца'),('spent','Гуляка таверны')):
            out[label]=[(r['name'],r['total']) for r in self.db.execute(f'SELECT p.name,COALESCE(SUM(l.{col}),0) AS total FROM players p LEFT JOIN ledger l ON l.uid=p.uid AND substr(l.day,1,7)=? WHERE p.approved=1 GROUP BY p.uid ORDER BY total DESC,p.uid LIMIT 30',(month,))]
        return out

    def snapshot(self):
        return json.dumps(self.rankings(),ensure_ascii=False)

    def backup(self, path):
        dest=sqlite3.connect(path)
        with dest: self.db.backup(dest)
        dest.close()
