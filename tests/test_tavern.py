import json
import sqlite3
import time
import unittest
from unittest.mock import patch
import test_engine as support
from engine import Engine,RuleError
from bot import Bot

class Tavern(unittest.TestCase):
    setUp=support.Rules.setUp
    tearDown=support.Rules.tearDown
    request=support.Rules.request
    def roy_request(self,uid=1,resource='base'):
        self.e.visit(uid);return self.e.request(uid,'roy_theft',{'resource':resource,'text':'Пробую стащить монеты'})
    def test_catalog_has_metadata_only_and_uncommon_count(self):
        pool=self.e.shop_pool('uncommon')
        self.assertEqual(len(pool),138)
        self.assertTrue(all(x['url'].startswith('https://next.dnd.su/items/') for x in pool))
        self.assertTrue(all('description' not in x for x in pool))
    def test_only_uncommon_open_by_default(self):
        self.assertEqual(self.e.shop_price('uncommon')['price'],400)
        self.assertFalse(self.e.shop_price('rare')['enabled'])
    def test_roy_success_takes_only_npc_gold(self):
        self.e.roy_adjust(99,1000,'Начальный кошелёк');rid=self.roy_request()
        with patch('tavern.secrets.randbelow',side_effect=[19,19,0]):r=self.e.roy_resolve(rid,5,7,0,14)
        self.assertTrue(r['success']);self.assertFalse(r['detected'])
        self.assertEqual(r['amount'],50);self.assertEqual(self.e.royal_gold(),950)
        self.assertEqual(self.e.player(1)['wallet'],10050);self.assertEqual(self.e.player(2)['wallet'],10000)
        self.assertEqual(self.e.rankings()['Заработок месяца'][0],('Герой 1',50))
    def test_roy_failure_consumes_action_but_no_money(self):
        self.e.roy_adjust(99,1000,'Кошелёк');rid=self.roy_request()
        with patch('tavern.secrets.randbelow',return_value=0):self.e.roy_resolve(rid,0,0,0,14)
        self.assertEqual(self.e.player(1)['turn'],0);self.assertEqual(self.e.royal_gold(),1000)
    def test_roy_no_stealth_detected(self):
        self.e.roy_adjust(99,1000,'Кошелёк');rid=self.roy_request()
        with patch('tavern.secrets.randbelow',return_value=19):r=self.e.roy_resolve(rid,None,0,0,14)
        self.assertTrue(r['detected'])
    def test_roy_empty_does_not_consume_action(self):
        rid=self.roy_request()
        with self.assertRaises(RuleError):self.e.roy_resolve(rid,0,0,0,14)
        self.assertEqual(self.e.player(1)['turn'],1)
    def test_roy_attempt_once_per_visit(self):
        self.e.roy_adjust(99,1000,'Кошелёк');rid=self.roy_request()
        with patch('tavern.secrets.randbelow',return_value=0):self.e.roy_resolve(rid,0,0,0,14)
        self.e.inspiration(1,1)
        rid2=self.e.request(1,'roy_theft',{'resource':'inspiration'})
        with self.assertRaises(RuleError):self.e.roy_resolve(rid2,0,0,0,14)
        self.assertEqual(self.e.player(1)['inspiration'],1)
    def test_roy_second_player_can_try_same_visit_day(self):
        self.e.roy_adjust(99,1000,'Кошелёк');r1=self.roy_request(1);r2=self.roy_request(2)
        with patch('tavern.secrets.randbelow',return_value=19):self.e.roy_resolve(r1,None,0,0,1);self.e.roy_resolve(r2,None,0,0,1)
        self.assertEqual(self.e.royal_gold(),900)
    def test_roy_last_coin_can_be_taken(self):
        self.e.roy_adjust(99,1,'Кошелёк');rid=self.roy_request()
        with patch('tavern.secrets.randbelow',return_value=19):self.e.roy_resolve(rid,None,0,0,1)
        self.assertEqual(self.e.royal_gold(),0);self.assertEqual(self.e.player(1)['wallet'],10001)
    def test_plain_approve_cannot_bypass_roy_checks(self):
        rid=self.roy_request()
        with self.assertRaises(RuleError):self.e.approve_request(rid)
        self.assertEqual(self.e.player(1)['turn'],1)
    def test_roy_result_only_once(self):
        self.e.roy_adjust(99,1000,'Кошелёк');rid=self.roy_request()
        with patch('tavern.secrets.randbelow',return_value=19):self.e.roy_resolve(rid,None,0,0,1)
        with self.assertRaises(RuleError):self.e.roy_resolve(rid,None,0,0,1)
        self.assertEqual(self.e.player(1)['wallet'],10050)
    def test_roy_and_ruble_balance_separate(self):
        self.e.support_update(99,'support_balance_rub','5000','Поддержка')
        self.e.roy_adjust(99,1000,'Игровой кошелёк');rid=self.roy_request()
        with patch('tavern.secrets.randbelow',return_value=19):self.e.roy_resolve(rid,None,0,0,1)
        self.assertEqual(self.e.meta_value('support_balance_rub'),'5000')
    def test_shop_prepare_takes_no_gold(self):
        o=self.e.shop_prepare(1,'uncommon')
        self.assertEqual(self.e.player(1)['wallet'],10000);self.assertEqual(o['count'],138)
    def test_shop_buy_is_atomic_item_and_expense(self):
        o=self.e.shop_prepare(1,'uncommon')
        with patch('tavern.secrets.randbelow',return_value=0):result=self.e.shop_buy(o['id'],1)
        self.assertEqual(self.e.player(1)['wallet'],9600)
        self.assertEqual(result['item']['owner'],1)
        self.assertEqual(result['item']['rarity'],'uncommon')
        self.assertEqual(self.e.rankings()['Гуляка таверны'][0],('Герой 1',400))
    def test_shop_repeated_confirmation_returns_same_item(self):
        o=self.e.shop_prepare(1,'uncommon');r1=self.e.shop_buy(o['id'],1);r2=self.e.shop_buy(o['id'],1)
        self.assertTrue(r2['already']);self.assertEqual(r1['item']['id'],r2['item']['id'])
        self.assertEqual(self.e.player(1)['wallet'],9600)
        self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM items WHERE owner=1').fetchone()[0],1)
    def test_shop_foreign_order_denied(self):
        o=self.e.shop_prepare(1,'uncommon')
        with self.assertRaises(RuleError):self.e.shop_buy(o['id'],2)
        self.assertEqual(self.e.player(2)['wallet'],10000)
    def test_shop_price_change_invalidates_order(self):
        o=self.e.shop_prepare(1,'uncommon');self.e.shop_set_price('uncommon',500)
        with self.assertRaises(RuleError):self.e.shop_buy(o['id'],1)
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_catalog_exclusion_invalidates_old_offer(self):
        o=self.e.shop_prepare(1,'uncommon');cid=self.e.shop_pool('uncommon')[0]['id'];self.e.shop_toggle(cid)
        with self.assertRaises(RuleError):self.e.shop_buy(o['id'],1)
        self.assertEqual(len(self.e.shop_pool('uncommon')),137)
    def test_closed_shelf_rejects_purchase(self):
        self.e.shop_set_price('uncommon',0)
        with self.assertRaises(RuleError):self.e.shop_prepare(1,'uncommon')
    def test_new_order_cancels_old_one(self):
        old=self.e.shop_prepare(1,'uncommon');self.e.shop_prepare(1,'uncommon')
        with self.assertRaises(RuleError):self.e.shop_buy(old['id'],1)
    def test_expired_offer_takes_no_money(self):
        o=self.e.shop_prepare(1,'uncommon')
        with patch('tavern.time.time',return_value=time.time()+601):
            with self.assertRaises(RuleError):self.e.shop_buy(o['id'],1)
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_failed_item_insert_rolls_back_debit(self):
        o=self.e.shop_prepare(1,'uncommon')
        self.e.db.execute("CREATE TRIGGER deny_item BEFORE INSERT ON items BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.e.shop_buy(o['id'],1)
        self.assertEqual(self.e.player(1)['wallet'],10000)
        self.assertEqual(self.e.shop_order(o['id'])['status'],'pending')
    def test_shop_respects_trade_reservations(self):
        tid=self.e.trade(1,2,9800,0,[],[],'резерв');self.e.confirm(tid,1);self.e.confirm(tid,2)
        with self.assertRaises(RuleError):self.e.shop_prepare(1,'uncommon')
    def test_shop_can_use_chest(self):
        self.request(1,'rent',{'tier':1});self.request(1,'storage',{'direction':'in','amount':1000})
        self.e.adjust(1,100,'Сверка',mode='set')
        o=self.e.shop_prepare(1,'uncommon');self.e.shop_buy(o['id'],1)
        self.assertEqual(self.e.player(1)['wallet'],0);self.assertEqual(self.e.player(1)['chest'],700)
    def test_shop_not_accessible_to_dead(self):
        self.e.life(1,True)
        with self.assertRaises(RuleError):self.e.shop_prepare(1,'uncommon')
    def test_shop_keeps_item_provenance_after_trade(self):
        o=self.e.shop_prepare(1,'uncommon');result=self.e.shop_buy(o['id'],1);iid=result['item']['id']
        tid=self.e.trade(1,2,0,0,[iid],[],'подарок');self.e.confirm(tid,1);self.e.confirm(tid,2);self.e.approve_request(tid)
        row=self.e.db.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
        self.assertEqual(row['owner'],2);self.assertTrue(row['source_url'].startswith('https://next.dnd.su/'))
    def test_catalog_exclusion_survives_restart(self):
        cid=self.e.shop_pool('uncommon')[0]['id'];self.e.shop_toggle(cid)
        self.e.db.close();self.e=Engine(self.tmp.name+'/test.db',lambda:self.today)
        self.assertEqual(len(self.e.shop_pool('uncommon')),137)
    def test_ruble_account_not_in_rankings(self):
        self.e.support_update(99,'support_balance_rub','1000000','Поддержка')
        self.assertTrue(all(x[1]==10000 for x in self.e.rankings()['Самые богатые']))
    def test_support_disabled_by_default(self):self.assertEqual(self.e.meta_value('support_enabled'),'0')
    def test_support_rejects_unsafe_url(self):
        with self.assertRaises(RuleError):self.e.support_update(99,'support_url','javascript:alert(1)')

class FeatureChat(unittest.TestCase):
    def setUp(self):
        support.Rules.setUp(self);self.api=support.FakeAPI();self.bot=Bot(self.api,self.e,{99},-100,7);self.n=500
    tearDown=support.Rules.tearDown
    def cmd(self,uid,text):
        self.n+=1;self.bot.handle(support.Transport.update(self,uid,text,self.n,True))
    def test_player_cannot_top_up_roy(self):
        self.cmd(1,'/ui royedit');self.cmd(1,'/roygold set 1000 | Подмена')
        self.assertEqual(self.e.royal_gold(),0)
    def test_player_cannot_change_shop(self):
        self.cmd(1,'/ui shopprice uncommon');self.cmd(1,'/shopprice uncommon 1')
        self.assertEqual(self.e.shop_price('uncommon')['price'],400)
    def test_player_cannot_change_rubles(self):
        self.cmd(1,'/ui supporttoggle 1');self.cmd(1,'/ui supportedit balance')
        self.assertEqual(self.e.meta_value('support_enabled'),'0')
    def test_roy_topup_needs_master_confirmation(self):
        self.cmd(99,'/ui royedit');self.cmd(99,'1000');self.cmd(99,'Фонд на кражи')
        self.assertEqual(self.e.royal_gold(),0)
        nonce=self.bot.ui_state(99)['payload']['nonce'];self.cmd(99,'/ui royconfirm '+nonce)
        self.assertEqual(self.e.royal_gold(),1000)
        self.cmd(99,'/ui royconfirm '+nonce);self.assertEqual(self.e.royal_gold(),1000)
    def test_support_balance_confirmation(self):
        self.cmd(99,'/ui supportedit balance');self.cmd(99,'500');self.cmd(99,'На сервер')
        self.assertEqual(self.e.meta_value('support_balance_rub'),'0')
        nonce=self.bot.ui_state(99)['payload']['nonce'];self.cmd(99,'/ui supportconfirm '+nonce)
        self.assertEqual(self.e.meta_value('support_balance_rub'),'500')
    def test_roy_resolution_command(self):
        self.e.roy_adjust(99,1000,'Кошелёк');self.e.visit(1)
        self.cmd(1,'/ui royattempt base')
        with patch('tavern.secrets.randbelow',return_value=19):self.cmd(99,'/royrob 1 none 7 2 14')
        self.assertEqual(self.e.req(1)['status'],'done');self.assertEqual(self.e.player(1)['wallet'],10050)
    def test_roy_request_has_correct_master_button(self):
        rid=self.e.request(1,'roy_theft',{'resource':'base'})
        _,buttons=self.bot.card(rid,99)
        self.assertIn('ui:royresolve:',json.dumps(buttons));self.assertNotIn('approve:',json.dumps(buttons))
    def test_shop_sends_one_public_announcement(self):
        self.cmd(1,'/ui shopoffer uncommon');self.cmd(1,'/ui shopbuy 1');self.cmd(1,'/ui shopbuy 1')
        rows=[r['text'] for r in self.e.db.execute('SELECT * FROM outbox WHERE target=-100') if 'НАХОДКА ИЗ ЛАВКИ' in r['text']]
        self.assertEqual(len(rows),1);self.assertEqual(self.e.player(1)['wallet'],9600)
    def test_support_page_shows_manual_rubles_without_rewards(self):
        self.e.support_update(99,'support_balance_rub','500','Поступление');self.e.support_update(99,'support_enabled','1')
        self.cmd(1,'/ui support')
        text=[kw['text'] for method,kw in self.api.calls if method=='sendMessage'][-1]
        self.assertIn('500 ₽',text);self.assertIn('вручную',text)
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_catalog_search_understands_cyrillic(self):
        self.cmd(99,'/ui catalogsearch');self.cmd(99,'брошь')
        text=str([kw for method,kw in self.api.calls if method=='sendMessage'][-1])
        self.assertIn('Брошь',text)

if __name__=='__main__':unittest.main()
