import json
import unittest
from datetime import timedelta
from unittest.mock import patch
import test_engine as support
from engine import Engine, RuleError
from bot import Bot
from character_interface import render_card

STATS=dict(ac=17,hp_now=30,hp_max=40,speed_ft=35,passive=12,weapons='Секретный клинок',bag='Секретная карта')

class Characters(unittest.TestCase):
    setUp=support.Rules.setUp
    tearDown=support.Rules.tearDown
    request=support.Rules.request

    def resurrect(self,target=1,sponsor=None):
        sponsor=target if sponsor is None else sponsor
        self.e.life(target,True)
        return self.e.res_pay(self.e.res_prepare(sponsor,target),sponsor)

    def test_new_card_unfilled(self):
        self.e.register(4,'Новый','Феникс');self.e.approve(4)
        self.assertFalse(self.e.card_ready(4))
        self.assertIsNone(self.e.char_data(4)['passive'])
        with self.assertRaises(RuleError):self.e.info_prepare(1,4)

    def test_character_request_requires_approval(self):
        rid=self.e.char_request(1,STATS)
        self.assertEqual(self.e.char_data(1)['ac'],14)
        self.e.approve_request(rid)
        self.assertEqual(self.e.char_data(1)['ac'],17)
        self.assertEqual(self.e.char_data(1)['hp_now'],30)
        with self.assertRaises(RuleError):self.e.approve_request(rid)

    def test_invalid_stats_rejected(self):
        for key,value in [('ac',-1),('hp_now',41),('hp_max',0),('passive',True),('speed_ft',1001),('bag',''),('weapons','x'*1201)]:
            with self.subTest(key=key),self.assertRaises(RuleError):self.e.char_request(1,dict(STATS,**{key:value}))

    def test_zero_hp_card_approval_marks_ghost_without_cancelling_itself(self):
        rid=self.e.char_request(1,dict(STATS,hp_now=0))
        self.e.approve_request(rid)
        self.assertEqual(self.e.req(rid)['status'],'done')
        self.assertTrue(self.e.player(1)['dead'])

    def test_hp_zero_cancels_trade_and_unrolled_action(self):
        self.e.visit(1)
        action=self.request(1,'action',dict(resource='base',text='Поиск'))
        trade=self.e.trade(1,2,100,0,[],[],'Обмен')
        self.e.set_hp(1,0)
        self.assertEqual(self.e.req(trade)['status'],'cancelled')
        self.assertEqual(self.e.req(action)['status'],'cancelled')
        self.assertEqual(self.e.char_data(1)['hp_now'],0)
        self.assertEqual(self.e.player(1)['turn'],0)
        with self.assertRaises(RuleError):self.e.check(action,0,10)

    def test_death_idempotent(self):
        self.e.life(1,True);seq=self.e.player(1)['death_seq']
        self.e.life(1,True)
        self.assertEqual(self.e.player(1)['death_seq'],seq)

    def test_ghost_cannot_trade_either_side(self):
        self.e.life(1,True)
        for a,b in [(1,2),(2,1)]:
            with self.assertRaises(RuleError):self.e.trade(a,b,1,0,[],[],'Нет')

    def test_ghost_cannot_request_actions_purchases_or_storage(self):
        self.e.life(1,True)
        for kind,payload in [('action',dict(resource='base',text='Нет')),('rent',dict(tier=1)),('spend',dict(amount=1,text='Нет')),('storage',dict(direction='in',amount=1)),('roy_theft',dict(resource='base'))]:
            with self.subTest(kind=kind),self.assertRaises(RuleError):self.e.request(1,kind,payload)
        with self.assertRaises(RuleError):self.e.info_prepare(1,2)
        with self.assertRaises(RuleError):self.e.char_request(1,STATS)

    def test_ghost_cannot_play_or_sponsor(self):
        self.e.life(1,True);self.e.life(2,True)
        with self.assertRaises(RuleError):self.e.poker_invite(1,3,10)
        with self.assertRaises(RuleError):self.e.res_prepare(1,2)

    def test_death_cancels_poker_with_refund_once(self):
        gid=self.e.poker_invite(1,2,100);self.e.poker_confirm(gid,2,1)
        self.e.life(1,True);self.e.life(1,True)
        self.assertEqual(self.e.poker_game(gid)['status'],'cancelled')
        self.assertEqual(self.e.player(1)['wallet'],10000)
        self.assertEqual(self.e.player(2)['wallet'],10000)
        with self.assertRaises(RuleError):self.e.poker_roll(gid,1)

    def test_cannot_revive_free_or_by_hp_edit(self):
        self.e.life(1,True)
        for fn in [lambda:self.e.revive(1,1),lambda:self.e.life(1,False),lambda:self.e.set_hp(1,10),lambda:self.e.apply_stats(1,STATS)]:
            with self.assertRaises(RuleError):fn()
        self.assertTrue(self.e.player(1)['dead'])
        self.assertEqual(self.e.player(1)['wallet'],10000)

    def test_master_can_fill_ghost_card_without_reviving(self):
        self.e.life(1,True)
        rid=self.e.char_request(1,dict(STATS,hp_now=0),editor=99);self.e.approve_request(rid)
        self.assertTrue(self.e.player(1)['dead']);self.assertEqual(self.e.char_data(1)['hp_max'],40)

    def test_paid_self_resurrection_full_hp_and_no_new_action(self):
        self.e.apply_stats(1,STATS);self.resurrect()
        self.assertFalse(self.e.player(1)['dead']);self.assertEqual(self.e.player(1)['wallet'],9000)
        self.assertEqual(self.e.char_data(1)['hp_now'],40);self.assertEqual(self.e.player(1)['turn'],0)
        self.assertEqual(self.e.weakness(1),-4)

    def test_sponsor_pays_not_target(self):
        self.resurrect(1,2)
        self.assertEqual(self.e.player(1)['wallet'],10000)
        self.assertEqual(self.e.player(2)['wallet'],9000)
        self.assertEqual(self.e.weakness(2),0)
        self.assertEqual(self.e.rankings()['Гуляка таверны'][0],('Герой 2',1000))

    def test_resurrection_receipt_is_idempotent_even_after_new_death(self):
        self.e.life(1,True);oid=self.e.res_prepare(1,1)
        self.assertEqual(self.e.res_pay(oid,1),(1,False))
        self.assertEqual(self.e.res_pay(oid,1),(1,True))
        self.e.life(1,True);self.e.res_pay(oid,1)
        self.assertTrue(self.e.player(1)['dead']);self.assertEqual(self.e.player(1)['wallet'],9000)

    def test_two_sponsors_only_one_pays(self):
        self.e.life(1,True);a=self.e.res_prepare(2,1);b=self.e.res_prepare(3,1)
        self.e.res_pay(a,2)
        with self.assertRaises(RuleError):self.e.res_pay(b,3)
        self.assertEqual(self.e.player(3)['wallet'],10000)

    def test_resurrection_foreign_button_and_expiry(self):
        self.e.life(1,True);oid=self.e.res_prepare(2,1)
        with self.assertRaises(RuleError):self.e.res_pay(oid,3)
        self.e.db.execute('UPDATE res_orders SET created=0 WHERE id=?',(oid,))
        with self.assertRaises(RuleError):self.e.res_pay(oid,2)
        self.assertTrue(self.e.player(1)['dead']);self.assertEqual(self.e.player(2)['wallet'],10000)

    def test_payment_insufficient_after_offer_is_atomic(self):
        self.e.life(1,True);oid=self.e.res_prepare(2,1)
        self.e.adjust(2,999,'Сверка',mode='set')
        with self.assertRaises(RuleError):self.e.res_pay(oid,2)
        self.assertTrue(self.e.player(1)['dead']);self.assertEqual(self.e.player(2)['wallet'],999)

    def test_payment_uses_wallet_then_chest(self):
        self.request(1,'rent',dict(tier=1));self.request(1,'storage',dict(direction='in',amount=1000))
        self.e.adjust(1,200,'Сверка',mode='set');self.resurrect()
        self.assertEqual(self.e.player(1)['wallet'],0);self.assertEqual(self.e.player(1)['chest'],200)

    def test_recovery_every_seven_days_not_weekday(self):
        self.resurrect();start=self.today
        for days,expected in [(0,-4),(6,-4),(7,-3),(13,-3),(14,-2),(21,-1),(28,0),(50,0)]:
            self.today=start+timedelta(days=days)
            self.assertEqual(self.e.weakness(1),expected)
        self.assertIsNone(self.e.weakness_next(1))

    def test_second_resurrection_resets_not_stacks(self):
        self.resurrect();self.today+=timedelta(days=14)
        self.assertEqual(self.e.weakness(1),-2)
        self.resurrect();self.assertEqual(self.e.weakness(1),-4)
        self.today+=timedelta(days=7);self.assertEqual(self.e.weakness(1),-3)

    def test_check_penalty_recorded_once_with_physical_die(self):
        self.resurrect();self.e.visit(1)
        rid=self.request(1,'action',dict(resource='base',text='Поиск'))
        r=self.e.check(rid,5,12,die=10)
        self.assertEqual((r['penalty'],r['base_modifier'],r['total']),(-4,5,11))
        self.assertFalse(r['success'])
        with self.assertRaises(RuleError):self.e.check(rid,5,12,die=20)

    def test_passive_12_requires_13(self):
        self.e.apply_stats(2,STATS);self.e.visit(1)
        with patch('engine.secrets.randbelow',side_effect=[11,19,0]):r=self.e.rob(1,2,1,'wallet',0,0,0,10)
        self.assertFalse(r['hidden']);self.assertTrue(r['detected'])

    def test_passive_12_hidden_at_13(self):
        self.e.apply_stats(2,STATS);self.e.visit(1)
        with patch('engine.secrets.randbelow',side_effect=[12,19,0]):r=self.e.rob(1,2,1,'wallet',0,0,0,10)
        self.assertTrue(r['hidden']);self.assertFalse(r['detected'])

    def test_theft_applies_penalties_and_preserves_passive(self):
        self.e.apply_stats(2,STATS);self.resurrect(1);self.resurrect(2);self.e.visit(1)
        with patch('engine.secrets.randbelow',side_effect=[15,15,15]):r=self.e.rob(1,2,1,'wallet',0,0,0,13)
        self.assertEqual((r['stealth'],r['hands'],r['perception']),(12,12,12))
        self.assertEqual(r['passive'],12);self.assertFalse(r['success'])

    def test_information_costs_once_and_is_fixed_snapshot(self):
        self.e.apply_stats(2,STATS);oid=self.e.info_prepare(1,2)
        snap,already=self.e.info_pay(oid,1)
        self.assertFalse(already);self.assertEqual(snap['ac'],17)
        self.e.apply_stats(2,dict(STATS,ac=18))
        self.assertEqual(self.e.info_saved(oid,1)['ac'],17)
        self.assertTrue(self.e.info_pay(oid,1)[1]);self.assertEqual(self.e.player(1)['wallet'],9500)
        oid2=self.e.info_prepare(1,2);self.assertEqual(self.e.info_pay(oid2,1)[0]['ac'],18)
        self.assertEqual(self.e.player(1)['wallet'],9000)

    def test_information_foreign_access_denied(self):
        oid=self.e.info_prepare(1,2)
        with self.assertRaises(RuleError):self.e.info_pay(oid,3)
        self.e.info_pay(oid,1)
        with self.assertRaises(RuleError):self.e.info_saved(oid,3)
        self.assertEqual(self.e.player(3)['wallet'],10000)

    def test_information_ghost_stale_button_denied(self):
        oid=self.e.info_prepare(1,2);self.e.life(1,True)
        with self.assertRaises(RuleError):self.e.info_pay(oid,1)
        self.assertEqual(self.e.player(1)['wallet'],10000)

    def test_snapshot_contains_equipment_without_gold(self):
        self.e.apply_stats(2,STATS);self.e.add_item(2,'Секретное кольцо')
        snap=self.e.info_pay(self.e.info_prepare(1,2),1)[0]
        text=render_card(snap)
        self.assertIn('Секретное кольцо',text);self.assertIn('Секретная карта',text)
        self.assertNotIn('wallet',snap);self.assertNotIn('custody',snap)

    def test_restart_preserves_penalty_and_paid_snapshot(self):
        self.resurrect();oid=self.e.info_prepare(1,2);self.e.info_pay(oid,1)
        self.e.backup(self.tmp.name+'/restart.db')
        other=Engine(self.tmp.name+'/restart.db',lambda:self.today)
        try:
            self.assertEqual(other.weakness(1),-4)
            self.assertEqual(other.info_saved(oid,1)['name'],'Герой 2')
        finally:other.db.close()

class CharacterUI(unittest.TestCase):
    tearDown=support.Rules.tearDown
    def setUp(self):
        support.Rules.setUp(self)
        self.api=support.FakeAPI();self.bot=Bot(self.api,self.e,{99},-100,7);self.n=100
        self.e.apply_stats(2,STATS)
    def cmd(self,uid,text,private=True):
        self.n+=1;self.bot.handle(support.Transport.update(self,uid,text,self.n,private))
    def texts(self):return '\n'.join(k.get('text','') for m,k in self.api.calls if m=='sendMessage')
    def test_public_profile_no_stat_disclosure(self):
        self.cmd(2,'/profile',False)
        self.assertNotIn('Секретный',self.texts());self.assertNotIn('Класс брони',self.texts())
    def test_player_cannot_inspect_or_admin_edit(self):
        self.cmd(1,'/inspect 2');self.cmd(1,'/ui charadmin 2');self.cmd(1,'/ui hpedit 2')
        self.assertNotIn('Секретный',self.texts())
        self.assertEqual(self.e.char_data(2)['hp_now'],30)
    def test_list_and_quote_only_names_no_stats(self):
        self.cmd(1,'/ui charlist');self.cmd(1,'/ui infooffer 2')
        self.assertNotIn('Секретный',self.texts());self.assertNotIn('35 футов',self.texts())
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_ghost_menu_hides_spending_and_poker(self):
        self.e.life(1,True);self.cmd(1,'/menu')
        markup=str(self.api.calls[-1][1].get('reply_markup',''))
        self.assertNotIn('poker',markup);self.assertNotIn('shop',markup);self.assertIn('resoffer',markup)
    def test_self_edit_wizard_requires_master(self):
        self.cmd(1,'/ui charedit')
        for value in ('17','30 40','35','12','Секретный клинок','Секретная карта'):self.cmd(1,value)
        row=self.e.db.execute("SELECT id FROM requests WHERE kind='character_update'").fetchone()
        self.assertIsNotNone(row);self.assertEqual(self.e.char_data(1)['ac'],14)
        self.cmd(99,'/approve '+str(row[0]));self.assertEqual(self.e.char_data(1)['ac'],17)
    def test_res_quote_does_not_disclose_hp_max(self):
        self.e.life(2,True);self.cmd(1,'/ui resoffer 2')
        self.assertNotIn('40',self.texts());self.assertNotIn('Секретный',self.texts())
    def test_res_public_notice_only_name(self):
        self.e.life(2,True);oid=self.e.res_prepare(1,2);self.cmd(1,'/ui respay '+str(oid))
        rows=self.e.db.execute('SELECT text FROM outbox WHERE target=-100').fetchall()
        self.assertTrue(rows)
        self.assertNotIn('Секретный',' '.join(r[0] for r in rows))

if __name__=='__main__':unittest.main()
