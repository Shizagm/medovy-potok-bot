import json
import unittest
from unittest.mock import patch
import test_engine as support
from bot import Bot

class Interface(unittest.TestCase):
    def setUp(self):
        support.Rules.setUp(self)
        self.api=support.FakeAPI();self.api.upload_animation=lambda *a,**kw:None
        self.bot=Bot(self.api,self.e,{99},-100,7)
        self.n=100
    tearDown=support.Rules.tearDown
    def cmd(self,uid,text,private=True):
        self.n+=1
        self.bot.handle(support.Transport.update(self,uid,text,self.n,private))
    def answer(self,uid,text):self.cmd(uid,text)
    def messages(self):return [kw for method,kw in self.api.calls if method=='sendMessage']
    def last(self):return self.messages()[-1]
    def test_menu_hides_admin_button_from_player(self):
        self.cmd(1,'/menu');card=self.last()
        self.assertIn('МЕДОВЫЙ ПОТОК',card['text'])
        self.assertNotIn('Стойка мастера',str(card['reply_markup']))
        self.assertNotIn('/act',card['text'])
    def test_master_without_character_has_admin_entry(self):
        self.cmd(99,'/menu')
        self.assertIn('Стойка мастера',str(self.last()['reply_markup']))
    def test_profile_has_readable_status_and_no_technical_id(self):
        self.cmd(1,'/profile');text=self.last()['text']
        self.assertIn('Основное действие: сейчас нет',text)
        self.assertNotIn('ID:',text);self.assertNotIn('0/0',text)
    def test_wallet_only_own_balances(self):
        self.cmd(1,'/ui wallet')
        self.assertIn('КОШЕЛЁК Герой 1',self.last()['text'])
        self.assertNotIn('Герой 2',self.last()['text'])
    def test_ordinary_user_admin_ui_denied(self):
        for text in ('/ui admin','/ui agold 1 income','/ui ainspire 1 1','/ui avisit 1','/ui boardedit','/ui backup','/ui adminplayer 2'):
            self.cmd(1,text)
        self.assertEqual(self.e.player(1)['wallet'],10000)
        self.assertEqual(self.e.player(1)['inspiration'],0)
        self.assertEqual(self.e.player(1)['turn'],0)
        self.assertIsNone(self.e.db.execute("SELECT 1 FROM meta WHERE key='backup_requested'").fetchone())
    def test_registration_guided_input(self):
        self.cmd(4,'/ui register');self.answer(4,'Лиара');self.answer(4,'Третий отряд')
        p=self.e.player(4,False)
        self.assertEqual(p['name'],'Лиара');self.assertEqual(p['party'],'Третий отряд')
        self.assertFalse(p['approved']);self.assertIsNone(self.bot.ui_state(4))
    def test_guided_action_creates_one_request(self):
        self.cmd(1,'/ui action base');self.answer(1,'Ищу записку у Роя')
        r=self.e.req(1)
        self.assertEqual(r['payload']['text'],'Ищу записку у Роя')
        self.assertEqual(self.e.player(1)['turn'],0)
        self.assertIsNone(self.bot.ui_state(1))
    def test_cancel_aborts_input(self):
        self.cmd(1,'/ui spend');self.cmd(1,'/ui cancel');self.answer(1,'100')
        self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],0)
    def test_guided_spend_requires_master(self):
        self.cmd(1,'/ui spend');self.answer(1,'50');self.answer(1,'Бочонок для гостей')
        r=self.e.req(1);self.assertEqual(r['status'],'pending')
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_guided_trade_uses_existing_confirmations(self):
        self.cmd(1,'/ui partner 2')
        for text in ('100','0','-','-','Подарок товарищу'):self.answer(1,text)
        r=self.e.req(1)
        self.assertEqual(r['kind'],'trade');self.assertEqual(r['payload']['give_gold'],100)
        self.assertEqual((r['ca'],r['cb']),(0,0))
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_admin_gold_requires_reason_and_confirmation(self):
        self.cmd(99,'/ui agold 1 income');self.answer(99,'200');self.answer(99,'Награда за миссию')
        self.assertEqual(self.e.player(1)['wallet'],10000)
        state=self.bot.ui_state(99);nonce=state['payload']['nonce']
        self.cmd(99,'/ui confirm '+nonce)
        self.assertEqual(self.e.player(1)['wallet'],10200)
        self.cmd(99,'/ui confirm '+nonce)
        self.assertEqual(self.e.player(1)['wallet'],10200)
    def test_stale_financial_confirmation_rejected(self):
        self.cmd(99,'/ui agold 1 income');self.answer(99,'200');self.answer(99,'Первая запись')
        old=self.bot.ui_state(99)['payload']['nonce']
        self.cmd(99,'/ui agold 1 income');self.answer(99,'500');self.answer(99,'Вторая запись')
        self.cmd(99,'/ui confirm '+old)
        self.assertEqual(self.e.player(1)['wallet'],10000)
        self.assertEqual(self.bot.ui_state(99)['payload']['amount'],500)
    def test_foreign_financial_button_denied(self):
        self.cmd(99,'/ui agold 1 income');self.answer(99,'200');self.answer(99,'Награда')
        nonce=self.bot.ui_state(99)['payload']['nonce'];self.cmd(1,'/ui confirm '+nonce)
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_board_edit_and_read(self):
        self.cmd(99,'/ui boardedit');self.answer(99,'Ищем пропавший ключ. Награда: Вдохновение Роя.')
        self.cmd(1,'/ui board')
        self.assertIn('пропавший ключ',self.last()['text'])
    def test_wrong_amount_keeps_input_open(self):
        self.cmd(1,'/ui storage in');self.answer(1,'не число')
        self.assertEqual(self.bot.ui_state(1)['flow'],'storage')
        self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],0)
    def test_expired_input_cannot_change_money(self):
        self.cmd(99,'/ui agold 1 income');self.answer(99,'200');self.answer(99,'Награда')
        nonce=self.bot.ui_state(99)['payload']['nonce']
        self.e.db.execute('UPDATE ui_sessions SET updated=0 WHERE uid=99')
        self.cmd(99,'/ui confirm '+nonce)
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_request_buttons_depend_on_viewer(self):
        rid=self.e.request(1,'action',{'resource':'base','text':'Проверка'})
        _,user=self.bot.card(rid,1);_,admin=self.bot.card(rid,99)
        self.assertNotIn('approve:',json.dumps(user))
        self.assertIn('approve:',json.dumps(admin))
    def test_group_menu_never_shows_private_wallet(self):
        self.cmd(1,'/ui wallet',False)
        self.assertNotIn('10000',str(self.last()))
    def test_master_guest_menu_can_approve(self):
        self.e.register(4,'Лиара','Отряд')
        self.cmd(99,'/ui admit 4');self.assertTrue(self.e.player(4)['approved'])
    def test_rent_button_only_creates_request(self):
        self.cmd(1,'/ui rent 2')
        self.assertEqual(self.e.player(1)['tier'],0)
        self.assertEqual(self.e.req(1)['payload']['tier'],2)
    def test_ui_callback_routes_safely(self):
        self.bot.handle({'update_id':999,'callback_query':{'id':'u','from':{'id':1},'data':'ui:wallet','message':{'chat':{'id':1,'type':'private'}}}})
        self.assertIn('КОШЕЛЁК',self.last()['text'])
    def test_group_text_not_treated_as_private_answer(self):
        self.cmd(1,'/ui action base');self.answer(1,'Проверка')
        self.cmd(1,'/ui spend');self.cmd(1,'100',private=False)
        self.assertEqual(self.bot.ui_state(1)['step'],0)

if __name__=='__main__':unittest.main()
