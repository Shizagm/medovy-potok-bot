import json
import unittest
from unittest.mock import patch
import test_engine as support
from bot import Bot

class ReadableChecks(unittest.TestCase):
    setUp=support.Rules.setUp
    tearDown=support.Rules.tearDown
    request=support.Rules.request
    def bot_ready(self):
        self.api=support.FakeAPI();self.bot=Bot(self.api,self.e,{99},-100,7)
        self.e.visit(1)
        return self.request(1,'action',dict(resource='base',text='Осматриваю стойку'))
    def run_cmd(self,text,n=200,uid=99):
        self.bot.handle(support.Transport.update(self,uid,text,n,True))
    def last_public(self):
        return self.e.db.execute('SELECT text FROM outbox WHERE target=-100 ORDER BY id DESC LIMIT 1').fetchone()[0]
    def test_physical_roll_names_actor_action_skill_and_full_arithmetic(self):
        self.e.life(1,True);self.e.res_pay(self.e.res_prepare(1,1),1)
        rid=self.bot_ready();self.run_cmd(f'/record {rid} 15 3 15 | Восприятие')
        text=self.last_public()
        for part in ('Герой: Герой 1','Действие: Осматриваю стойку','ПРОВЕРКА: Восприятие','15 + 3 − 4 = 14','Сложность: 15','Неудача'):
            self.assertIn(part,text)
        self.assertNotIn('№',text)
    def test_original_command_still_works(self):
        rid=self.bot_ready();self.run_cmd(f'/record {rid} 15 3 15')
        self.assertIn('ПРОВЕРКА ДЕЙСТВИЯ',self.last_public())
        self.assertIn('15 + 3 = 18',self.last_public())
        self.assertNotIn('№',self.last_public())
    def test_d20_animation_retained_without_public_request_number(self):
        rid=self.bot_ready()
        with patch('engine.secrets.randbelow',return_value=9):self.run_cmd(f'/check {rid} 2 10 | Анализ')
        text=self.last_public();self.assertTrue(text.startswith('@ANIMATION@'))
        media=json.loads(text[len('@ANIMATION@'):])
        self.assertEqual(media['file'],'d20-10.gif')
        self.assertIn('ПРОВЕРКА: Анализ',media['caption']);self.assertNotIn('№',media['caption'])
    def test_askroll_context_and_skill_survive_player_button(self):
        rid=self.bot_ready();self.run_cmd(f'/askroll {rid} 2 10 | Восприятие')
        group=[kw['text'] for method,kw in self.api.calls if method=='sendMessage' and kw['chat_id']==-100][-1]
        self.assertIn('Герой: Герой 1',group);self.assertIn('Действие: Осматриваю стойку',group)
        self.assertNotIn('№',group)
        with patch('engine.secrets.randbelow',return_value=9):self.run_cmd(f'/roll {rid}',201,1)
        media=json.loads(self.last_public()[len('@ANIMATION@'):])
        self.assertIn('ПРОВЕРКА: Восприятие',media['caption'])
    def test_repeat_roll_does_not_create_second_result(self):
        rid=self.bot_ready();self.run_cmd(f'/record {rid} 15 3 15 | Восприятие')
        count=self.e.db.execute('SELECT count(*) FROM outbox WHERE target=-100').fetchone()[0]
        self.run_cmd(f'/record {rid} 20 10 15 | Другой навык',201)
        self.assertEqual(self.e.db.execute('SELECT count(*) FROM outbox WHERE target=-100').fetchone()[0],count)
        self.assertEqual(self.e.req(rid)['payload']['check_name'],'Восприятие')
    def test_invalid_label_does_not_consume_roll(self):
        rid=self.bot_ready();self.run_cmd(f'/record {rid} 15 3 15 | '+('x'*81))
        self.assertIsNone(self.e.req(rid)['rolled'])
    def test_negative_modifier_does_not_show_plus_negative(self):
        rid=self.bot_ready();self.run_cmd(f'/record {rid} 15 -2 15')
        self.assertIn('15 − 2 = 13',self.last_public())
        self.assertNotIn('+ -',self.last_public())
    def test_master_request_card_keeps_number(self):
        rid=self.bot_ready()
        self.assertIn('№'+str(rid),self.bot.card(rid,99)[0])

if __name__=='__main__':unittest.main()
