import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from engine import Engine, RuleError
from bot import Bot, TelegramError

class Rules(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.today=date(2026,11,4)
        self.e=Engine(self.tmp.name+'/test.db',lambda:self.today)
        for uid in (1,2,3):
            self.e.register(uid,'Герой '+str(uid),'Феникс'); self.e.approve(uid)
            self.e.adjust(uid,10000,'Начальный баланс')
            self.e.apply_stats(uid,{'ac':14,'hp_now':20,'hp_max':20,'speed_ft':30,'passive':10,'weapons':'Меч','bag':'Рюкзак'})
    def tearDown(self): self.e.db.close(); self.tmp.cleanup()
    def request(self,uid,kind,p):
        rid=self.e.request(uid,kind,p); self.e.approve_request(rid); return rid
    def trade(self,amount=100,items=None):
        rid=self.e.trade(1,2,amount,0,items or [],[],'обмен')
        self.e.confirm(rid,1); self.e.confirm(rid,2); return rid
    def test_inspiration_single_and_nonstacking(self):
        self.e.inspiration(1,1)
        with self.assertRaises(RuleError): self.e.inspiration(1,1)
        self.e.visit(1)
        rid=self.e.request(1,'action',dict(resource='inspiration',text='действую'))
        with self.assertRaises(RuleError): self.e.approve_request(rid)
        self.request(1,'action',dict(resource='base',text='первый ход'))
        self.e.approve_request(rid)
        self.assertEqual(self.e.player(1)['inspiration'],0)
        with self.assertRaises(RuleError): self.e.approve_request(rid)
        self.e.inspiration(1,1)
        r=self.e.request(1,'action',dict(resource='inspiration',text='ещё'))
        with self.assertRaises(RuleError): self.e.approve_request(r)
    def test_visit_once_per_day(self):
        self.e.visit(1)
        with self.assertRaises(RuleError): self.e.visit(1)
    def test_trade_requires_both_and_is_atomic(self):
        item=self.e.add_item(1,'Артефакт')
        rid=self.e.trade(1,2,100,0,[item],[],'дар')
        self.e.confirm(rid,1)
        with self.assertRaises(RuleError): self.e.approve_request(rid)
        self.assertEqual(self.e.player(1)['wallet'],10000)
        self.e.confirm(rid,2); self.e.approve_request(rid)
        self.assertEqual(self.e.player(1)['wallet'],9900)
        self.assertEqual(self.e.player(2)['wallet'],10100)
        self.assertEqual(self.e.db.execute('SELECT owner FROM items WHERE id=?',(item,)).fetchone()[0],2)
        with self.assertRaises(RuleError): self.e.approve_request(rid)
    def test_outsider_confirmation_denied(self):
        rid=self.e.trade(1,2,100,0,[],[],'подарок')
        with self.assertRaises(RuleError): self.e.confirm(rid,3)
    def test_gold_and_items_reserved(self):
        item=self.e.add_item(1,'меч'); self.trade(9900,[item])
        with self.assertRaises(RuleError): self.e.trade(1,3,200,0,[],[],'нет')
        with self.assertRaises(RuleError): self.e.trade(1,3,0,0,[item],[],'нет')
        with self.assertRaises(RuleError): self.request(1,'spend',dict(amount=200,text='пир'))
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_cancellation_releases_reservation(self):
        rid=self.trade(9900); self.e.cancel(rid,1)
        self.request(1,'spend',dict(amount=200,text='пир'))
        self.assertEqual(self.e.player(1)['wallet'],9800)
    def test_adjustment_cancels_pending_trade(self):
        rid=self.trade(9900); self.e.adjust(1,-9000,'ошибка')
        self.assertEqual(self.e.req(rid)['status'],'cancelled')
    def test_no_negative_money(self):
        with self.assertRaises(RuleError): self.e.adjust(1,-10001,'нет')
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_room_caps_and_storage_no_rank_income(self):
        for tier,cap in ((1,1000),(2,5000),(3,10000)):
            self.request(1,'rent',dict(tier=tier))
            self.request(1,'storage',dict(direction='in',amount=cap))
            with self.assertRaises(RuleError): self.request(1,'storage',dict(direction='in',amount=1))
            self.request(1,'storage',dict(direction='out',amount=cap))
        self.assertEqual(self.e.rankings()['Заработок месяца'][0][1],0)
    def test_cannot_downgrade_full_chest(self):
        self.request(1,'rent',dict(tier=3)); self.request(1,'storage',dict(direction='in',amount=5001))
        with self.assertRaises(RuleError): self.request(1,'rent',dict(tier=2))
    def test_weekly_daily_rate_and_idempotency(self):
        self.request(1,'rent',dict(tier=1))
        self.today+=timedelta(days=7); self.e.settle()
        self.assertEqual(self.e.player(1)['wallet'],10000-147)
        self.e.settle(); self.assertEqual(self.e.player(1)['wallet'],10000-147)
        self.assertEqual(self.e.player(2)['wallet'],9993)
    def test_food_first_then_chest(self):
        self.request(1,'rent',dict(tier=1)); self.request(1,'storage',dict(direction='in',amount=1000))
        self.e.adjust(1,0,'сверка',mode='set'); self.today+=timedelta(days=1); self.e.settle()
        self.assertEqual(self.e.player(1)['chest'],979)
    def test_insufficient_rent_no_debt(self):
        self.request(1,'rent',dict(tier=1)); self.e.adjust(1,10,'сверка',mode='set')
        self.today+=timedelta(days=7); self.e.settle(); p=self.e.player(1)
        self.assertEqual(p['tier'],0); self.assertEqual(p['wallet'],3)
    def test_eviction_preserves_custody(self):
        self.request(1,'rent',dict(tier=3)); self.request(1,'storage',dict(direction='in',amount=50))
        self.e.adjust(1,0,'сверка',mode='set'); self.today+=timedelta(days=1); self.e.settle()
        self.assertEqual(self.e.player(1)['custody'],49)
        self.e.reclaim(1); self.assertEqual(self.e.player(1)['wallet'],49)
    def test_dead_no_food_but_rent(self):
        self.request(1,'rent',dict(tier=1)); self.e.life(1,True)
        self.today+=timedelta(days=7); self.e.settle()
        self.assertEqual(self.e.player(1)['wallet'],9860)
    def test_paid_revival_costs_gold_and_keeps_turn(self):
        self.e.life(1,True);self.e.visit(1);oid=self.e.res_prepare(1,1);self.e.res_pay(oid,1)
        self.assertEqual(self.e.player(1)['dead'],0);self.assertEqual(self.e.player(1)['turn'],1)
        self.assertEqual(self.e.player(1)['wallet'],9000)
    def test_roll_only_once(self):
        self.e.visit(1); rid=self.request(1,'action',dict(resource='base',text='проверка'))
        with patch('engine.secrets.randbelow',return_value=9): r=self.e.check(rid,3,13)
        self.assertTrue(r['success']); self.assertEqual(r['total'],13)
        with self.assertRaises(RuleError): self.e.check(rid,3,13)
    def test_theft_rank_and_anonymity(self):
        self.e.visit(1)
        with patch('engine.secrets.randbelow',side_effect=[19,19,0]): r=self.e.rob(1,2,50,'wallet',5,7,0,14)
        self.assertTrue(r['success']); self.assertFalse(r['detected'])
        self.assertEqual(self.e.player(1)['wallet'],10050); self.assertEqual(self.e.player(2)['wallet'],9950)
        self.assertEqual(self.e.rankings()['Заработок месяца'][0],('Герой 1',50))
        victim_msgs=[r[0] for r in self.e.db.execute('SELECT text FROM outbox WHERE target=2')]
        self.assertNotIn('Герой 1',' '.join(victim_msgs))
    def test_theft_no_stealth_detected(self):
        self.e.visit(1)
        with patch('engine.secrets.randbelow',return_value=0): r=self.e.rob(1,2,50,'wallet',None,0,0,14)
        self.assertFalse(r['success']); self.assertTrue(r['detected'])
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_theft_cap_and_cooldown(self):
        self.e.visit(1)
        with self.assertRaises(RuleError): self.e.rob(1,2,51,'wallet',0,0,0,1)
        with patch('engine.secrets.randbelow',return_value=19): self.e.rob(1,2,50,'wallet',0,0,0,1)
        self.e.visit(3)
        with self.assertRaises(RuleError): self.e.rob(3,2,20,'wallet',0,0,0,1)
    def test_month_boundary_and_refunds(self):
        self.e.adjust(1,200,'награда',earned=True); self.e.adjust(1,-50,'пир',spent=True)
        self.e.rank_adjust(1,0,-50,'возврат')
        self.assertEqual(self.e.rankings()['Гуляка таверны'][0][1],0)
        self.today=date(2026,12,1)
        self.assertEqual(self.e.rankings()['Заработок месяца'][0][1],0)
        self.assertEqual(self.e.rankings('2026-11')['Заработок месяца'][0][1],200)
    def test_rent_change_charges_old_days(self):
        self.request(1,'rent',dict(tier=1)); self.today+=timedelta(days=2)
        self.request(1,'rent',dict(tier=2)); self.today+=timedelta(days=1); self.e.settle()
        self.assertEqual(self.e.player(1)['wallet'],10000-42-51)
    def test_snapshot_is_stale_until_publish(self):
        old=self.e.snapshot(); self.e.adjust(1,100,'награда',earned=True)
        self.assertNotEqual(old,self.e.snapshot())
    def test_pause_stops_billing_and_actions(self):
        self.request(1,'rent',dict(tier=1)); self.e.pause(1,1)
        self.today+=timedelta(days=7); self.e.settle()
        self.assertEqual(self.e.player(1)['wallet'],10000)
        self.e.visit(1)
        with self.assertRaises(RuleError):self.e.request(1,'action',dict(resource='base',text='нет'))
        self.e.pause(1,0); self.today+=timedelta(days=1); self.e.settle()
        self.assertEqual(self.e.player(1)['wallet'],9979)
    def test_backup_and_restart(self):
        self.e.inspiration(1,1); rid=self.trade(); self.e.backup(self.tmp.name+'/copy.db')
        other=Engine(self.tmp.name+'/copy.db',lambda:self.today)
        self.assertEqual(other.player(1)['inspiration'],1)
        self.assertEqual(other.req(rid)['ca'],1); other.db.close()
    def test_weekly_catchup(self):
        self.today=date(2026,11,23); self.e.weekly()
        self.assertEqual(self.e.player(1)['wallet'],9981)
        self.e.weekly(); self.assertEqual(self.e.player(1)['wallet'],9981)

class FakeAPI:
    def __init__(self): self.calls=[]
    def call(self,method,**kw):
        self.calls.append((method,kw))
        if method=='getChatMember': return {'status':'member'}
        return {'message_id':1}

class Transport(unittest.TestCase):
    tearDown=Rules.tearDown
    trade=Rules.trade
    def setUp(self):
        Rules.setUp(self); self.api=FakeAPI(); self.bot=Bot(self.api,self.e,{99},-100,7)
    def update(self,uid,text,n=1,private=True):
        return {'update_id':n,'message':{'message_id':n,'from':{'id':uid},'chat':{'id':uid if private else -100,'type':'private' if private else 'supergroup'},'text':text}}
    def test_unauthorized_admin(self):
        self.bot.handle(self.update(1,'/gold 1 delta 999 income | нет'))
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_callback_not_party(self):
        rid=self.trade()
        self.bot.handle({'update_id':5,'callback_query':{'id':'x','from':{'id':3},'data':f'confirm:{rid}','message':{'chat':{'id':3,'type':'private'}}}})
        self.assertTrue(any('не участник' in x[1].get('text','') for x in self.api.calls))
    def test_telegram_failure_rolls_back_gold(self):
        original=self.api.call
        def fail(method,**kw):
            if method=='sendMessage': raise TelegramError('test')
            return original(method,**kw)
        self.api.call=fail
        with self.assertRaises(TelegramError): self.bot.handle(self.update(99,'/gold 1 delta 999 income | награда'))
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_group_profile_does_not_leak(self):
        self.bot.handle(self.update(1,'/profile',private=False))
        self.assertFalse(any('Кошелёк:' in x[1].get('text','') for x in self.api.calls))
    def test_publish_no_theft_identity(self):
        with self.e.tx(): self.bot.publish()
        text=self.e.db.execute("SELECT value FROM meta WHERE key='public_ranks'").fetchone()[0]
        self.assertNotIn('кошелёк',text.lower())
    def test_duplicate_update_not_applied_twice(self):
        u=self.update(99,'/gold 1 delta 100 income | награда')
        self.bot.handle(u); self.bot.handle(u)
        self.assertEqual(self.e.player(1)['wallet'],10100)
    def test_rob_command_format(self):
        self.e.visit(1)
        with patch('engine.secrets.randbelow',return_value=19):
            self.bot.handle(self.update(99,'/rob 1 2 wallet 30 5 7 2 14'))
        self.assertEqual(self.e.player(1)['wallet'],10030)
    def test_admin_command_works(self):
        self.bot.handle(self.update(99,'/gold 1 delta 999 income | награда'))
        self.assertEqual(self.e.player(1)['wallet'],10999)

if __name__=='__main__': unittest.main()
