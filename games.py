"""Optional player checks and non-redeemable fictional-gold dice poker."""
import json
import secrets
import time
from collections import Counter


def poker_score(dice):
    if len(dice)!=5 or any(type(x) is not int or not 1<=x<=6 for x in dice):
        raise ValueError('Нужно пять d6.')
    counts=Counter(dice)
    groups=sorted(((n,value) for value,n in counts.items()),reverse=True)
    sizes=sorted(counts.values(),reverse=True)
    if sizes==[5]: return (7,groups[0][1]),'Пять одинаковых'
    if sizes==[4,1]: return (6,*[v for n,v in groups]),'Каре'
    if sizes==[3,2]: return (5,*[v for n,v in groups]),'Фулл-хаус'
    if sorted(dice) in ([1,2,3,4,5],[2,3,4,5,6]): return (4,max(dice)),'Стрит'
    if sizes==[3,1,1]: return (3,*[v for n,v in groups]),'Тройка'
    if sizes==[2,2,1]: return (2,*[v for n,v in groups]),'Две пары'
    if sizes==[2,1,1,1]: return (1,*[v for n,v in groups]),'Пара'
    return (0,*sorted(dice,reverse=True)),'Старшие кости'


class GamesMixin:
    def games_schema(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS assigned_checks(
          rid INTEGER PRIMARY KEY REFERENCES requests(id), modifier INTEGER NOT NULL,
          dc INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS poker(
          id INTEGER PRIMARY KEY, a INTEGER NOT NULL REFERENCES players(uid),
          b INTEGER NOT NULL REFERENCES players(uid), stake INTEGER NOT NULL CHECK(stake>0),
          ca INTEGER NOT NULL DEFAULT 0, cb INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'invited', da TEXT, db TEXT,
          created INTEGER NOT NULL, result TEXT);
        ''')
        self.upgrade_poker()

    def upgrade_poker(self):
        fields={'ra':'INTEGER NOT NULL DEFAULT 0','rb':'INTEGER NOT NULL DEFAULT 0',
                'ma':'INTEGER NOT NULL DEFAULT 0','mb':'INTEGER NOT NULL DEFAULT 0',
                'ready_a':'INTEGER NOT NULL DEFAULT 0','ready_b':'INTEGER NOT NULL DEFAULT 0',
                'show_a':'INTEGER NOT NULL DEFAULT 0','show_b':'INTEGER NOT NULL DEFAULT 0',
                'rev_a':'INTEGER NOT NULL DEFAULT 0','rev_b':'INTEGER NOT NULL DEFAULT 0',
                'version':'INTEGER NOT NULL DEFAULT 1','deadline':'INTEGER NOT NULL DEFAULT 0'}
        existing={r[1] for r in self.db.execute('PRAGMA table_info(poker)')}
        for name,spec in fields.items():
            if name not in existing:self.db.execute(f'ALTER TABLE poker ADD COLUMN {name} {spec}')
        if not self.db.execute("SELECT 1 FROM meta WHERE key='poker_v4'").fetchone():
            with self.tx():
                for row in self.db.execute("SELECT id FROM poker WHERE status IN ('invited','active')").fetchall():
                    self._poker_cancel(row['id'],'обновление правил покера; создайте новый вызов')
                self.db.execute("INSERT INTO meta VALUES('poker_v4','1')")

    def assign_check(self, rid, modifier, dc):
        with self.tx():
            r=self.req(rid)
            if r['kind']!='action' or r['status']!='done' or r['rolled']:
                raise self.error('Нужна одобренная заявка без результата броска.')
            if self.db.execute('SELECT 1 FROM assigned_checks WHERE rid=?',(rid,)).fetchone():
                raise self.error('Проверка уже назначена: параметры менять нельзя.')
            self.db.execute('INSERT INTO assigned_checks VALUES(?,?,?)',(rid,modifier,dc))

    def player_roll(self, rid, uid):
        with self.tx():
            r=self.req(rid)
            if r['a']!=uid: raise self.error('Этот бросок назначен другому герою.')
            c=self.db.execute('SELECT * FROM assigned_checks WHERE rid=?',(rid,)).fetchone()
            if not c: raise self.error('Мастер ещё не назначил проверку.')
            return self.check(rid,c['modifier'],c['dc'])

    def poker_game(self, gid):
        row=self.db.execute('SELECT * FROM poker WHERE id=?',(gid,)).fetchone()
        if not row: raise self.error('Стол не найден.')
        return dict(row)

    def _poker_held(self, uid):
        # Pending offers reserve nothing. On acceptance both contributions go to escrow.
        return 0

    def _poker_available(self, uid):
        p=self.player(uid); held,_=self._held(uid)
        return p['wallet']+p['chest']-held

    def _poker_live(self, uid):
        p=self.player(uid)
        if p['dead'] or p['paused']:raise self.error('Играть может живой активный герой.')
        return p

    def _poker_side(self, g, uid):
        if uid==g['a']:return 'a'
        if uid==g['b']:return 'b'
        raise self.error('Ты не участник этой партии.')

    def _poker_active(self, gid, uid, revision=None):
        self.require_alive(uid)
        g=self.poker_game(gid);side=self._poker_side(g,uid)
        if g['status']!='active':raise self.error('Сейчас нельзя менять кости: партия не активна.')
        if int(time.time())>=g['deadline']:raise self.error('Время партии истекло; бот скоро подведёт итог.')
        if g['ready_'+side]:raise self.error('Комбинация уже подтверждена и не меняется.')
        if revision is not None and revision!=g['rev_'+side]:raise self.error('Это старая карточка руки. Открой /pokerview '+str(gid))
        return g,side

    def _cancel_poker_for_user(self, uid, reason):
        # Active escrows are independent of bills and wallet corrections.
        for row in self.db.execute("SELECT id FROM poker WHERE status='invited' AND (a=? OR b=?)",(uid,uid)).fetchall():
            self._poker_cancel(row['id'],reason)

    def _poker_cancel(self, gid, reason):
        g=self.poker_game(gid)
        if g['status'] not in ('invited','active','showdown'):raise self.error('Партия уже закрыта.')
        if g['status'] in ('active','showdown'):
            for who in (g['a'],g['b']):
                self.db.execute('UPDATE players SET wallet=wallet+? WHERE uid=?',(g['stake'],who))
                self.log(who,'poker_refund',g['stake'],f'Возврат ставки: стол №{gid}')
        self.db.execute("UPDATE poker SET status='cancelled',result=? WHERE id=?",(reason,gid))
        for who in (g['a'],g['b']):self.notify(who,f'Стол №{gid} отменён: {reason}. Ставки возвращены, если партия была начата.')

    def poker_cancel(self, gid, uid, admin=False):
        with self.tx():
            g=self.poker_game(gid)
            if not admin:self.require_alive(uid);self._poker_side(g,uid)
            if g['status'] in ('active','showdown') and not admin:
                raise self.error('Ставки уже приняты. Можно сдаться: /pokerfold '+str(gid))
            self._poker_cancel(gid,'отказ от вызова' if not admin else 'решение мастера')

    def poker_invite(self, a, b, stake):
        if a==b or not 1<=stake<=100000:raise self.error('Нужен другой герой и ставка 1–100000 зм.')
        with self.tx():
            for who in (a,b):
                self._poker_live(who)
                if self.db.execute("SELECT 1 FROM poker WHERE status IN ('invited','active','showdown') AND (a=? OR b=?)",(who,who)).fetchone():
                    raise self.error('У участника уже есть незавершённая партия.')
                if self._poker_available(who)<stake:raise self.error('Не хватает доступного золота у одного из участников.')
            now=int(time.time())
            cur=self.db.execute('INSERT INTO poker(a,b,stake,ca,created,deadline) VALUES(?,?,?,1,?,?)',(a,b,stake,now,now+86400))
            return cur.lastrowid

    def poker_offer(self, gid, uid, stake, version):
        if not 1<=stake<=100000:raise self.error('Ставка: 1–100000 зм.')
        with self.tx():
            g=self.poker_game(gid);side=self._poker_side(g,uid)
            if g['status']!='invited' or version!=g['version']:raise self.error('Предложение устарело или игра уже началась.')
            if int(time.time())>=g['deadline']:raise self.error('Вызов истёк.')
            for who in (g['a'],g['b']):
                self._poker_live(who)
                if self._poker_available(who)<stake:raise self.error('Не хватает доступного золота.')
            self.db.execute('UPDATE poker SET stake=?,ca=?,cb=?,version=version+1,deadline=? WHERE id=?',
                (stake,int(side=='a'),int(side=='b'),int(time.time())+86400,gid))
            return self.poker_game(gid)

    def _poker_debit(self, uid, amount, gid):
        p=self.player(uid);held,_=self._held(uid)
        free_wallet=max(0,p['wallet']-held)
        wallet=min(free_wallet,amount);chest=amount-wallet
        if chest>p['chest']:raise self.error('Недостаточно доступного золота.')
        self.db.execute('UPDATE players SET wallet=wallet-?,chest=chest-? WHERE uid=?',(wallet,chest,uid))
        self.log(uid,'poker_stake',-amount,f'Ставка: стол №{gid}; кошелёк {wallet}, сундук {chest}')

    def poker_confirm(self, gid, uid, version):
        with self.tx():
            g=self.poker_game(gid);side=self._poker_side(g,uid)
            if g['status']!='invited' or version!=g['version']:raise self.error('Эта ставка уже неактуальна. Открой текущий стол.')
            if int(time.time())>=g['deadline']:raise self.error('Вызов истёк.')
            if g['c'+side]:raise self.error('Ты уже согласился; ждём второго игрока.')
            # Validate both before debiting either. No master approval is needed.
            for who in (g['a'],g['b']):
                self._poker_live(who)
                if self._poker_available(who)<g['stake']:raise self.error('Баланс изменился: ставки нельзя принять.')
            self.db.execute(f'UPDATE poker SET c{side}=1 WHERE id=?',(gid,))
            g=self.poker_game(gid)
            if g['ca'] and g['cb']:
                self._poker_debit(g['a'],g['stake'],gid);self._poker_debit(g['b'],g['stake'],gid)
                self.db.execute("UPDATE poker SET status='active',deadline=? WHERE id=?",(int(time.time())+86400,gid))
            return self.poker_game(gid)

    def poker_roll(self, gid, uid, revision=None):
        with self.tx():
            g,side=self._poker_active(gid,uid,revision)
            if g['d'+side]:raise self.error('Первый бросок уже сделан; выбирай кости для переброса.')
            dice=[secrets.randbelow(6)+1 for _ in range(5)]
            self.db.execute(f'UPDATE poker SET d{side}=?,rev_{side}=rev_{side}+1,deadline=? WHERE id=?',
                (json.dumps(dice),int(time.time())+86400,gid))
            return self.poker_game(gid)

    def poker_pick(self, gid, uid, position, revision):
        if not 1<=position<=5:raise self.error('Номер кости: 1–5.')
        with self.tx():
            g,side=self._poker_active(gid,uid,revision)
            if not g['d'+side] or g['r'+side]>=2:raise self.error('Нет доступного переброса.')
            mask=g['m'+side]^(1<<(position-1))
            self.db.execute(f'UPDATE poker SET m{side}=?,rev_{side}=rev_{side}+1 WHERE id=?',(mask,gid))
            return self.poker_game(gid)

    def poker_reroll(self, gid, uid, revision):
        with self.tx():
            g,side=self._poker_active(gid,uid,revision)
            if not g['d'+side] or g['r'+side]>=2:raise self.error('Два переброса уже использованы.')
            if not g['m'+side]:raise self.error('Сначала отметь хотя бы одну кость.')
            dice=json.loads(g['d'+side])
            for i in range(5):
                if g['m'+side]&(1<<i):dice[i]=secrets.randbelow(6)+1
            self.db.execute(f'UPDATE poker SET d{side}=?,r{side}=r{side}+1,m{side}=0,rev_{side}=rev_{side}+1,deadline=? WHERE id=?',
                (json.dumps(dice),int(time.time())+86400,gid))
            return self.poker_game(gid)

    def poker_lock(self, gid, uid, revision):
        with self.tx():
            g,side=self._poker_active(gid,uid,revision)
            if not g['d'+side]:raise self.error('Сначала брось пять костей.')
            self.db.execute(f'UPDATE poker SET ready_{side}=1,m{side}=0,rev_{side}=rev_{side}+1,deadline=? WHERE id=?',(int(time.time())+86400,gid))
            g=self.poker_game(gid)
            if g['ready_a'] and g['ready_b']:
                self.db.execute("UPDATE poker SET status='showdown' WHERE id=?",(gid,))
            return self.poker_game(gid)

    def _poker_finish(self, gid, winner, reason, reveal=True):
        g=self.poker_game(gid)
        if g['status'] not in ('active','showdown'):raise self.error('Партия уже рассчитана.')
        da=json.loads(g['da']) if g['da'] else None;db=json.loads(g['db']) if g['db'] else None
        la=poker_score(da)[1] if da else 'Нет броска';lb=poker_score(db)[1] if db else 'Нет броска'
        result=dict(winner=winner,la=la,lb=lb,da=da,db=db,bank=g['stake']*2,reason=reason,reveal=reveal)
        if winner is None:
            for who in (g['a'],g['b']):
                self.db.execute('UPDATE players SET wallet=wallet+? WHERE uid=?',(g['stake'],who))
                self.log(who,'poker_tie',g['stake'],f'Возврат ставки: стол №{gid}; {reason}')
        else:
            loser=g['b'] if winner==g['a'] else g['a']
            self.db.execute('UPDATE players SET wallet=wallet+? WHERE uid=?',(g['stake']*2,winner))
            self.log(winner,'poker_win',g['stake']*2,f'Стол №{gid}: банк {g["stake"]*2}, чистый выигрыш {g["stake"]}; {reason}',earned=g['stake'])
            self.log(loser,'poker_loss',0,f'Стол №{gid}: проиграна ставка {g["stake"]}; {reason}',spent=g['stake'])
        self.db.execute("UPDATE poker SET status='done',result=? WHERE id=?",(json.dumps(result,ensure_ascii=False),gid))
        for who in (g['a'],g['b']):self.notify(who,f'Покер №{gid} завершён. {reason}. /pokerview {gid}')
        return self.poker_game(gid)

    def _poker_compare(self, gid, reason):
        g=self.poker_game(gid)
        if not g['da'] and not g['db']:winner=None
        elif not g['da']:winner=g['b']
        elif not g['db']:winner=g['a']
        else:
            sa=poker_score(json.loads(g['da']))[0];sb=poker_score(json.loads(g['db']))[0]
            winner=g['a'] if sa>sb else g['b'] if sb>sa else None
        return self._poker_finish(gid,winner,reason)

    def poker_show(self, gid, uid):
        self.require_alive(uid)
        with self.tx():
            g=self.poker_game(gid);side=self._poker_side(g,uid)
            if g['status']!='showdown':raise self.error('Сначала оба должны подтвердить комбинации.')
            if int(time.time())>=g['deadline']:raise self.error('Время истекло; бот скоро вскроет стол.')
            if g['show_'+side]:raise self.error('Ты уже готов к вскрытию.')
            self.db.execute(f'UPDATE poker SET show_{side}=1 WHERE id=?',(gid,))
            g=self.poker_game(gid)
            if g['show_a'] and g['show_b']:return self._poker_compare(gid,'Общее вскрытие')
            return g

    def poker_fold(self, gid, uid):
        self.require_alive(uid)
        with self.tx():
            g=self.poker_game(gid);side=self._poker_side(g,uid)
            if g['status'] not in ('active','showdown'):raise self.error('Партия не активна.')
            return self._poker_finish(gid,g['b'] if side=='a' else g['a'],'Соперник сдался',reveal=False)

    def expire_poker(self):
        changed=[]
        with self.tx():
            for row in self.db.execute("SELECT id,status FROM poker WHERE status IN ('invited','active','showdown') AND deadline<=?",(int(time.time()),)).fetchall():
                if row['status']=='invited':self._poker_cancel(row['id'],'вызов истёк через 24 часа')
                else:self._poker_compare(row['id'],'Автоматический расчёт после 24 часов без хода')
                changed.append(row['id'])
        return changed
