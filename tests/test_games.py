import json
import sqlite3
import time
import unittest
from unittest.mock import patch
import test_engine as support
from engine import Engine,RuleError
from games import poker_score

class Poker(unittest.TestCase):
    setUp=support.Rules.setUp
    tearDown=support.Rules.tearDown
    request=support.Rules.request
    def ready(self,stake=100):
        gid=self.e.poker_invite(1,2,stake)
        self.e.poker_confirm(gid,2,1)
        return gid
    def dice(self,gid,uid,values):
        with patch('games.secrets.randbelow',side_effect=[x-1 for x in values]):
            return self.e.poker_roll(gid,uid)
    def lock(self,gid,uid):
        g=self.e.poker_game(gid);side=self.e._poker_side(g,uid)
        return self.e.poker_lock(gid,uid,g['rev_'+side])
    def finish(self,gid):
        self.lock(gid,1);self.lock(gid,2)
        self.e.poker_show(gid,1)
        return self.e.poker_show(gid,2)
    def test_hierarchy(self):
        hands=[[1,2,3,4,6],[1,1,2,3,4],[1,1,2,2,3],[1,1,1,2,3],[1,2,3,4,5],[1,1,1,2,2],[1,1,1,1,2],[1,1,1,1,1]]
        self.assertEqual([poker_score(h)[0][0] for h in hands],list(range(8)))
    def test_all_7776_hands_classified_consistently(self):
        from itertools import product
        from collections import Counter
        counts=Counter();canonical={}
        for dice in product(range(1,7),repeat=5):
            score,label=poker_score(dice);counts[score[0]]+=1
            key=tuple(sorted(dice))
            if key in canonical:self.assertEqual(canonical[key],score)
            canonical[key]=score
        self.assertEqual(dict(counts),{7:6,6:150,5:300,4:240,3:1200,2:1800,1:3600,0:480})
    def test_tiebreaks(self):
        self.assertGreater(poker_score([2,3,4,5,6])[0],poker_score([1,2,3,4,5])[0])
        self.assertGreater(poker_score([6,6,6,1,1])[0],poker_score([5,5,5,6,6])[0])
        self.assertGreater(poker_score([6,6,4,4,1])[0],poker_score([6,6,3,3,5])[0])
    def test_accept_starts_without_master(self):
        gid=self.ready();g=self.e.poker_game(gid)
        self.assertEqual(g['status'],'active');self.assertEqual(self.e.player(1)['wallet'],9900)
        self.assertEqual(self.e.player(2)['wallet'],9900)
    def test_no_debit_before_acceptance(self):
        gid=self.e.poker_invite(1,2,100)
        self.assertEqual(self.e.player(1)['wallet'],10000);self.assertEqual(self.e._held(1)[0],0)
        self.assertEqual(self.e.poker_game(gid)['ca'],1)
    def test_counteroffer_resets_consent(self):
        gid=self.e.poker_invite(1,2,100)
        g=self.e.poker_offer(gid,2,250,1)
        self.assertEqual((g['ca'],g['cb'],g['version']),(0,1,2))
        self.e.poker_confirm(gid,1,2)
        self.assertEqual(self.e.player(1)['wallet'],9750)
    def test_old_offer_button_rejected(self):
        gid=self.e.poker_invite(1,2,100);self.e.poker_offer(gid,1,300,1)
        with self.assertRaises(RuleError):self.e.poker_confirm(gid,2,1)
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_outsider_cannot_accept(self):
        gid=self.e.poker_invite(1,2,100)
        with self.assertRaises(RuleError):self.e.poker_confirm(gid,3,1)
    def test_duplicate_acceptance_no_double_debit(self):
        gid=self.ready()
        with self.assertRaises(RuleError):self.e.poker_confirm(gid,2,1)
        self.assertEqual(self.e.player(1)['wallet'],9900)
    def test_insufficient_at_acceptance_atomic(self):
        gid=self.e.poker_invite(1,2,100)
        # Simulate a legitimate spend after the offer, without cancelling the invitation.
        self.request(1,'spend',dict(amount=9950,text='покупка'))
        with self.assertRaises(RuleError):self.e.poker_confirm(gid,2,1)
        self.assertEqual(self.e.player(2)['wallet'],10000)
        self.assertEqual(self.e.poker_game(gid)['status'],'invited')
    def test_budget_uses_wallet_then_chest(self):
        self.request(1,'rent',dict(tier=1));self.request(1,'storage',dict(direction='in',amount=500))
        self.e.adjust(1,20,'остаток',mode='set')
        gid=self.ready(100)
        self.assertEqual(self.e.player(1)['wallet'],0);self.assertEqual(self.e.player(1)['chest'],420)
    def test_does_not_spend_reserved_trade_money(self):
        tid=self.e.trade(1,3,9900,0,[],[],'резерв');self.e.confirm(tid,1);self.e.confirm(tid,3)
        with self.assertRaises(RuleError):self.e.poker_invite(1,2,101)
        gid=self.ready(100)
        self.assertEqual(self.e.player(1)['wallet'],9900)
        self.e.approve_request(tid)
        self.assertEqual(self.e.player(1)['wallet'],0)
    def test_does_not_use_roy_custody(self):
        self.e.adjust(1,0,'остаток',mode='set')
        self.e.db.execute('UPDATE players SET custody=10000 WHERE uid=1')
        with self.assertRaises(RuleError):self.ready(1)
    def test_select_and_reroll_only_marked(self):
        gid=self.ready();g=self.dice(gid,1,[1,2,3,4,5])
        g=self.e.poker_pick(gid,1,2,g['rev_a']);g=self.e.poker_pick(gid,1,5,g['rev_a'])
        with patch('games.secrets.randbelow',side_effect=[5,5]):g=self.e.poker_reroll(gid,1,g['rev_a'])
        self.assertEqual(json.loads(g['da']),[1,6,3,4,6]);self.assertEqual(g['ra'],1);self.assertEqual(g['ma'],0)
    def test_two_rerolls_max(self):
        gid=self.ready();g=self.dice(gid,1,[1]*5)
        for n in range(2):
            g=self.e.poker_pick(gid,1,1,g['rev_a']);g=self.e.poker_reroll(gid,1,g['rev_a'])
        with self.assertRaises(RuleError):self.e.poker_pick(gid,1,1,g['rev_a'])
        with self.assertRaises(RuleError):self.e.poker_reroll(gid,1,g['rev_a'])
    def test_stale_hand_buttons_rejected(self):
        gid=self.ready();g=self.dice(gid,1,[1]*5);revision=g['rev_a']
        self.e.poker_pick(gid,1,1,revision)
        with self.assertRaises(RuleError):self.e.poker_pick(gid,1,2,revision)
    def test_cannot_reroll_without_selection(self):
        gid=self.ready();g=self.dice(gid,1,[1]*5)
        with self.assertRaises(RuleError):self.e.poker_reroll(gid,1,g['rev_a'])
        self.assertEqual(self.e.poker_game(gid)['ra'],0)
    def test_initial_roll_only_once(self):
        gid=self.ready();self.dice(gid,1,[1]*5)
        with self.assertRaises(RuleError):self.e.poker_roll(gid,1)
    def test_ready_hand_immutable(self):
        gid=self.ready();self.dice(gid,1,[1]*5);self.lock(gid,1)
        with self.assertRaises(RuleError):self.e.poker_pick(gid,1,1,self.e.poker_game(gid)['rev_a'])
        with self.assertRaises(RuleError):self.e.poker_reroll(gid,1,self.e.poker_game(gid)['rev_a'])
    def test_cannot_lock_without_roll(self):
        gid=self.ready()
        with self.assertRaises(RuleError):self.lock(gid,1)
    def test_no_payout_before_both_show(self):
        gid=self.ready();self.dice(gid,1,[6]*5);self.dice(gid,2,[1]*5)
        self.lock(gid,1);self.lock(gid,2);self.e.poker_show(gid,1)
        self.assertEqual(self.e.player(1)['wallet'],9900)
        self.assertEqual(self.e.poker_game(gid)['status'],'showdown')
    def test_winner_paid_once_and_ranked_by_profit(self):
        gid=self.ready();self.dice(gid,1,[6]*5);self.dice(gid,2,[1]*5);g=self.finish(gid)
        self.assertEqual(json.loads(g['result'])['winner'],1)
        self.assertEqual(self.e.player(1)['wallet'],10100);self.assertEqual(self.e.player(2)['wallet'],9900)
        self.assertEqual(self.e.rankings()['Заработок месяца'][0],('Герой 1',100))
        self.assertEqual(self.e.rankings()['Гуляка таверны'][0],('Герой 2',100))
        with self.assertRaises(RuleError):self.e.poker_show(gid,2)
        with self.assertRaises(RuleError):self.e.poker_fold(gid,1)
        self.assertEqual(self.e.player(1)['wallet']+self.e.player(2)['wallet'],20000)
    def test_tie_refunds_and_no_rank(self):
        gid=self.ready();self.dice(gid,1,[3]*5);self.dice(gid,2,[3]*5);self.finish(gid)
        self.assertEqual(self.e.player(1)['wallet'],10000);self.assertEqual(self.e.player(2)['wallet'],10000)
        self.assertTrue(all(n==0 for _,n in self.e.rankings()['Заработок месяца']))
    def test_fold_costs_stake_and_hides_hands(self):
        gid=self.ready();self.dice(gid,1,[6]*5);g=self.e.poker_fold(gid,1)
        self.assertEqual(self.e.player(2)['wallet'],10100)
        self.assertFalse(json.loads(g['result'])['reveal'])
    def test_active_player_cannot_cancel_for_refund(self):
        gid=self.ready()
        with self.assertRaises(RuleError):self.e.poker_cancel(gid,1)
    def test_master_emergency_refund(self):
        gid=self.ready();self.e.poker_cancel(gid,99,True)
        self.assertEqual(self.e.player(1)['wallet'],10000)
        with self.assertRaises(RuleError):self.e.poker_cancel(gid,99,True)
    def test_timeout_no_rolls_refund(self):
        gid=self.ready()
        with patch('games.time.time',return_value=time.time()+86401):changed=self.e.expire_poker()
        self.assertIn(gid,changed);self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_timeout_one_roll_wins(self):
        gid=self.ready();self.dice(gid,1,[1]*5)
        with patch('games.time.time',return_value=time.time()+86401):self.e.expire_poker()
        self.assertEqual(self.e.player(1)['wallet'],10100)
    def test_timeout_two_hands_auto_compares(self):
        gid=self.ready();self.dice(gid,1,[6]*5);self.dice(gid,2,[1]*5)
        with patch('games.time.time',return_value=time.time()+86401):self.e.expire_poker()
        self.assertEqual(self.e.player(1)['wallet'],10100)
    def test_timeout_blocks_late_reroll(self):
        gid=self.ready();g=self.dice(gid,1,[1]*5);g=self.e.poker_pick(gid,1,1,g['rev_a'])
        with patch('games.time.time',return_value=time.time()+86401):
            with self.assertRaises(RuleError):self.e.poker_reroll(gid,1,g['rev_a'])
    def test_invite_expires_without_money_change(self):
        gid=self.e.poker_invite(1,2,100)
        with patch('games.time.time',return_value=time.time()+86401):self.e.expire_poker()
        self.assertEqual(self.e.poker_game(gid)['status'],'cancelled');self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_wealth_includes_escrow(self):
        self.ready()
        self.assertTrue(all(n==10000 for _,n in self.e.rankings()['Самые богатые']))
    def test_pending_offer_cancelled_on_correction(self):
        gid=self.e.poker_invite(1,2,100);self.e.adjust(1,-1,'сверка')
        self.assertEqual(self.e.poker_game(gid)['status'],'cancelled')
    def test_duplicate_table_rejected(self):
        self.e.poker_invite(1,2,100)
        with self.assertRaises(RuleError):self.e.poker_invite(1,3,100)
    def test_restart_preserves_hand_rerolls_and_escrow(self):
        gid=self.ready();g=self.dice(gid,1,[1]*5);g=self.e.poker_pick(gid,1,2,g['rev_a']);self.e.poker_reroll(gid,1,g['rev_a'])
        old=self.e.poker_game(gid);self.e.db.close();self.e=Engine(self.tmp.name+'/test.db',lambda:self.today)
        new=self.e.poker_game(gid)
        self.assertEqual(old,new);self.assertEqual(self.e.player(1)['wallet'],9900)
    def test_legacy_live_games_refunded_once(self):
        gid=self.ready();self.e.db.execute("DELETE FROM meta WHERE key='poker_v4'")
        self.e.db.close();self.e=Engine(self.tmp.name+'/test.db',lambda:self.today)
        self.assertEqual(self.e.poker_game(gid)['status'],'cancelled');self.assertEqual(self.e.player(1)['wallet'],10000)
        self.e.db.close();self.e=Engine(self.tmp.name+'/test.db',lambda:self.today)
        self.assertEqual(self.e.player(1)['wallet'],10000)

class Checks(unittest.TestCase):
    setUp=support.Rules.setUp
    tearDown=support.Rules.tearDown
    request=support.Rules.request
    def action(self):
        self.e.visit(1);return self.request(1,'action',dict(resource='base',text='Осмотр'))
    def test_assigned_roll_owner_only(self):
        rid=self.action();self.e.assign_check(rid,3,14)
        with self.assertRaises(RuleError):self.e.player_roll(rid,2)
        self.e.player_roll(rid,1)
        with self.assertRaises(RuleError):self.e.player_roll(rid,1)
    def test_physical_roll_recorded_once(self):
        rid=self.action();r=self.e.check(rid,3,14,die=12)
        self.assertEqual(r['source'],'table');self.assertEqual(r['total'],15)
        with self.assertRaises(RuleError):self.e.check(rid,3,14,die=20)

class ChatCommands(unittest.TestCase):
    def setUp(self):
        support.Rules.setUp(self)
        self.api=support.FakeAPI();self.api.upload_animation=lambda *a,**kw:None
        from bot import Bot
        self.bot=Bot(self.api,self.e,{99},-100,7)
    tearDown=support.Rules.tearDown
    update=support.Transport.update
    def ready(self):
        gid=self.e.poker_invite(1,2,100);self.e.poker_confirm(gid,2,1);return gid
    def test_no_public_hands_before_showdown(self):
        gid=self.ready()
        with patch('games.secrets.randbelow',side_effect=[0,0,0,0,0]):self.e.poker_roll(gid,1)
        text,_=self.bot.poker_card(gid)
        self.assertNotIn('1 · 1 · 1 · 1 · 1',text)
        own,_=self.bot.poker_card(gid,1);other,_=self.bot.poker_card(gid,2)
        self.assertIn('1 · 1 · 1 · 1 · 1',own);self.assertNotIn('1 · 1 · 1 · 1 · 1',other)
    def test_outsider_cannot_get_private_hand(self):
        gid=self.ready()
        with self.assertRaises(RuleError):self.bot.poker_card(gid,3)
    def test_hidden_cards_sent_to_owners_only(self):
        gid=self.ready()
        with patch('games.secrets.randbelow',return_value=0):self.e.poker_roll(gid,1)
        self.bot.post_poker(gid)
        for row in self.e.db.execute('SELECT target,text FROM outbox'):
            if '1 · 1 · 1 · 1 · 1' in row['text']:self.assertEqual(row['target'],1)
    def test_player_accept_callback_autostarts(self):
        self.bot.handle(self.update(1,'/poker 2 100',n=1))
        self.bot.handle(self.update(2,'/pokerconfirm 1 1',n=2,private=False))
        self.assertEqual(self.e.poker_game(1)['status'],'active')
    def test_group_roll_never_sends_hand_to_group(self):
        gid=self.ready()
        with patch('games.secrets.randbelow',return_value=0):self.bot.handle(self.update(1,f'/pokerroll {gid} 0',n=1,private=False))
        for row in self.e.db.execute('SELECT target,text FROM outbox WHERE target=-100'):
            self.assertNotIn('1 · 1 · 1 · 1 · 1',row['text'])
    def test_forged_pick_other_hand_rejected(self):
        gid=self.ready();self.e.poker_roll(gid,1)
        before=self.e.poker_game(gid)
        self.bot.handle(self.update(3,f'/pokerpick {gid} {before["rev_a"]} 1',n=1))
        self.assertEqual(self.e.poker_game(gid),before)
    def test_menu_has_names_not_other_balances(self):
        self.bot.handle(self.update(1,'/poker',n=1))
        text=self.e.db.execute('SELECT text FROM outbox WHERE target=1 ORDER BY id DESC LIMIT 1').fetchone()[0]
        self.assertIn('Герой 2',text);self.assertNotIn('10000',text)
    def test_public_card_edits_existing_message(self):
        gid=self.ready();self.bot.post_poker(gid);self.bot.housekeeping()
        self.e.poker_roll(gid,1);self.bot.post_poker(gid);self.bot.housekeeping()
        self.assertTrue(any(method=='editMessageText' and kw['chat_id']==-100 for method,kw in self.api.calls))
    def test_complete_game_through_chat_commands(self):
        self.bot.handle(self.update(1,'/poker 2 100',n=1))
        self.bot.handle(self.update(2,'/pokerconfirm 1 1',n=2))
        with patch('games.secrets.randbelow',side_effect=[5]*5+[0]*5):
            self.bot.handle(self.update(1,'/pokerroll 1 0',n=3))
            self.bot.handle(self.update(2,'/pokerroll 1 0',n=4))
        self.bot.handle(self.update(1,'/pokerlock 1 1',n=5))
        self.bot.handle(self.update(2,'/pokerlock 1 1',n=6))
        self.bot.handle(self.update(1,'/pokershow 1',n=7))
        self.bot.handle(self.update(2,'/pokershow 1',n=8))
        self.assertEqual(self.e.player(1)['wallet'],10100)
        self.assertEqual(self.e.poker_game(1)['status'],'done')
        public,_=self.bot.poker_card(1)
        self.assertIn('6 · 6 · 6 · 6 · 6',public)
    def test_pick_callback_routes_revision_and_position(self):
        gid=self.ready();self.e.poker_roll(gid,1)
        self.bot.handle({'update_id':1,'callback_query':{'id':'x','from':{'id':1},'data':f'pokerpick:{gid}:1:3','message':{'chat':{'id':1,'type':'private'}}}})
        self.assertEqual(self.e.poker_game(gid)['ma'],4)
    def test_old_accept_callback_cannot_accept_new_stake(self):
        gid=self.e.poker_invite(1,2,100);self.e.poker_offer(gid,1,300,1)
        self.bot.handle({'update_id':1,'callback_query':{'id':'x','from':{'id':2},'data':f'pokerconfirm:{gid}:1','message':{'chat':{'id':-100,'type':'supergroup'}}}})
        self.assertEqual(self.e.poker_game(gid)['status'],'invited')
        self.assertEqual(self.e.player(2)['wallet'],10000)
    def test_restart_keeps_old_profile_and_adds_new_columns(self):
        self.e.db.execute('DROP TABLE poker');self.e.db.execute("DELETE FROM meta WHERE key='poker_v4'")
        self.e.db.executescript('CREATE TABLE poker(id INTEGER PRIMARY KEY,a INTEGER,b INTEGER,stake INTEGER,ca INTEGER DEFAULT 0,cb INTEGER DEFAULT 0,status TEXT DEFAULT "invited",da TEXT,db TEXT,created INTEGER,result TEXT);')
        self.e.db.close();self.e=Engine(self.tmp.name+'/test.db',lambda:self.today)
        self.assertEqual(self.e.player(1)['wallet'],10000)
        self.assertIn('ready_a',[x[1] for x in self.e.db.execute('PRAGMA table_info(poker)')])

if __name__=='__main__':unittest.main()
