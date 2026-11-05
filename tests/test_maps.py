import io,json,sqlite3,tempfile,unittest,struct,zlib
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
import test_engine as support
from engine import Engine,RuleError
from bot import Bot
from map_rules import cell,coord
from map_render import render_map

class Maps(unittest.TestCase):
    setUp=support.Rules.setUp
    tearDown=support.Rules.tearDown
    request=support.Rules.request
    def place(self,uid,value,area='hall'):self.e.map_set_position(uid,area,value)
    def move(self,uid,value,area='hall'):
        order=self.e.map_prepare(uid,area,value)
        return self.e.map_commit(uid,order['id'])[0]
    def test_coordinates(self):
        self.assertEqual(coord(' l16 '),(11,15));self.assertEqual(cell(11,15),'L16')
        for value in ('А1','AA1','A0','1A','Z100'):
            with self.assertRaises(ValueError):coord(value)
    def test_schema_default_does_not_change_old_gameplay(self):
        self.assertFalse(self.e.map_enabled())
        self.assertEqual(self.e.meta_value('map_weekly'),'0')
        self.assertTrue(self.e.map_data()['draft'])
        self.place(2,'B2');rid=self.e.trade(1,2,1,0,[],[],'Старая схема')
        self.assertEqual(self.e.req(rid)['status'],'pending')
    def test_spawn_and_no_free_movement(self):
        pos=self.e.map_position(1)
        self.assertEqual((pos['area'],cell(pos['x'],pos['y']),pos['remaining']),('hall','L16',0))
        with self.assertRaises(RuleError):self.e.map_prepare(1,'hall','L15')
    def test_visit_uses_speed_and_does_not_spend_action(self):
        self.e.visit(1);r=self.move(1,'L13')
        self.assertEqual((r['cost'],r['remaining']),(3,3))
        self.assertEqual(self.e.player(1)['turn'],1)
    def test_path_past_budget_moves_only_available_segment(self):
        self.e.visit(1);order=self.e.map_prepare(1,'hall','C16')
        self.assertEqual((order['cost'],order['total']),(6,9))
        r=self.e.map_commit(1,order['id'])[0]
        self.assertEqual((r['cell'],r['remaining']),('F16',0))
    def test_remaining_movement_can_be_spent_in_parts(self):
        self.e.visit(1);self.move(1,'K16');r=self.move(1,'J16')
        self.assertEqual(r['remaining'],4)
    def test_diagonal_cost_one(self):
        self.e.visit(1);r=self.move(1,'M15')
        self.assertEqual(r['cost'],1)
    def test_no_wall_walk(self):
        self.e.visit(1)
        with self.assertRaises(RuleError):self.e.map_prepare(1,'hall','K10')
    def test_no_corner_cut(self):
        data=self.e.map_data();f=data['floors']['hall'];rows=list(map(list,f['rows']));rows[14][11]='#';rows[15][12]='#';f['rows']=[''.join(row) for row in rows];self.e.map_save(data)
        start=('hall',11,15);target=('hall',12,14)
        self.assertNotIn(target,list(self.e.map_neighbors(start,False,self.e.map_data())))
        self.assertIn(target,list(self.e.map_neighbors(start,True,self.e.map_data())))
    def test_closed_kitchen_has_no_route_then_open_works(self):
        self.e.visit(1)
        with self.assertRaises(RuleError):self.e.map_prepare(1,'hall','C3')
        self.e.map_door('kitchen',1)
        order=self.e.map_prepare(1,'hall','C3');self.assertGreater(order['total'],6)
    def test_no_closing_door_on_living_guest(self):
        self.e.map_door('kitchen',1);self.place(1,'F7')
        with self.assertRaises(RuleError):self.e.map_door('kitchen',0)
    def test_ghost_can_fly_through_walls_but_not_unknown(self):
        self.e.life(1,True);self.e.map_grant(1);self.place(1,'J10')
        r=self.move(1,'K10');self.assertEqual(r['cost'],1)
        with self.assertRaises(RuleError):self.e.map_prepare(1,'cellar','B2')
    def test_resurrection_in_wall_returns_to_portal(self):
        self.e.life(1,True);self.place(1,'K10');self.e.res_pay(self.e.res_prepare(1,1),1)
        pos=self.e.map_position(1)
        self.assertEqual((pos['area'],cell(pos['x'],pos['y'])),('hall','L16'))
        self.assertEqual(self.e.player(1)['wallet'],9000)
        self.assertFalse(self.e.player(1)['dead'])

    def test_cellar_reveal_keeps_underlying_wall_and_no_names_leak(self):
        snap=self.e.map_snapshot(1,'cellar')
        self.assertTrue(all(set(row)=={'?'} for row in snap['tiles']))
        self.assertEqual(snap['people'],[])
        self.e.map_reveal('cellar','A1','C3')
        snap=self.e.map_snapshot(1,'cellar')
        self.assertEqual(snap['tiles'][0][0],'#');self.assertEqual(snap['tiles'][1][1],'.')
        self.assertEqual(snap['tiles'][3][3],'?')
    def test_stairs_link_costs_one_and_floor_changes(self):
        self.place(1,'W3');self.e.map_grant(1)
        r=self.move(1,'W10','rooms');self.assertEqual((r['area'],r['cost']),('rooms',1))
    def test_hidden_cellar_blocks_stairs_until_revealed(self):
        self.e.map_door('kitchen',1);self.place(1,'C3');self.e.map_grant(1)
        with self.assertRaises(RuleError):self.e.map_prepare(1,'cellar','B2')
        self.e.map_reveal('cellar','B2','D4');r=self.move(1,'B2','cellar')
        self.assertEqual(r['cost'],1)
    def test_double_confirmation_does_not_move_again(self):
        self.e.visit(1);o=self.e.map_prepare(1,'hall','K16')
        first=self.e.map_commit(1,o['id']);self.assertFalse(first[1])
        self.assertTrue(self.e.map_commit(1,o['id'])[1])
        self.assertEqual(self.e.map_position(1)['remaining'],5)
        self.assertEqual(self.e.db.execute("SELECT count(*) FROM ledger WHERE kind='movement'").fetchone()[0],1)
    def test_foreign_confirmation_denied(self):
        self.e.visit(1);o=self.e.map_prepare(1,'hall','K16')
        with self.assertRaises(RuleError):self.e.map_commit(2,o['id'])
        self.assertEqual(self.e.map_position(1)['remaining'],6)
    def test_old_route_cancelled_by_new_preview(self):
        self.e.visit(1);o=self.e.map_prepare(1,'hall','K16');self.e.map_prepare(1,'hall','M16')
        with self.assertRaises(RuleError):self.e.map_commit(1,o['id'])
    def test_door_change_invalidates_preview(self):
        self.e.visit(1);o=self.e.map_prepare(1,'hall','K16');self.e.map_door('kitchen',1)
        with self.assertRaises(RuleError):self.e.map_commit(1,o['id'])
    def test_expired_route_does_not_spend(self):
        self.e.visit(1);o=self.e.map_prepare(1,'hall','K16');self.e.db.execute('UPDATE map_orders SET created=0')
        with self.assertRaises(RuleError):self.e.map_commit(1,o['id'])
        self.assertEqual(self.e.map_position(1)['remaining'],6)
    def test_master_placement_invalidates_preview(self):
        self.e.visit(1);o=self.e.map_prepare(1,'hall','K16');self.place(1,'M16')
        with self.assertRaises(RuleError):self.e.map_commit(1,o['id'])
    def test_death_invalidates_preview(self):
        self.e.visit(1);o=self.e.map_prepare(1,'hall','K16');self.e.life(1,True)
        with self.assertRaises(RuleError):self.e.map_commit(1,o['id'])
    def test_grant_invalidates_preview(self):
        self.e.visit(1);o=self.e.map_prepare(1,'hall','K16');self.e.map_grant(1)
        with self.assertRaises(RuleError):self.e.map_commit(1,o['id'])
    def test_pause_denies_flight_and_move(self):
        self.e.visit(1);o=self.e.map_prepare(1,'hall','K16');self.e.pause(1,1)
        with self.assertRaises(RuleError):self.e.map_commit(1,o['id'])
        with self.assertRaises(RuleError):self.e.map_grant(1)
    def test_trade_requires_nearby_on_create(self):
        self.e.map_enable(1);self.place(2,'C16')
        with self.assertRaises(RuleError):self.e.trade(1,2,1,0,[],[],'Далеко')
    def test_trade_checks_again_on_master_approval(self):
        self.e.map_enable(1);self.place(2,'K16');rid=self.e.trade(1,2,10,0,[],[],'Рядом')
        self.e.confirm(rid,1);self.e.confirm(rid,2);self.place(2,'C16')
        with self.assertRaises(RuleError):self.e.approve_request(rid)
        self.assertEqual(self.e.player(1)['wallet'],10000)
        self.assertEqual(self.e.player(2)['wallet'],10000)
    def test_trade_success_nearby(self):
        self.e.map_enable(1);self.place(2,'K16');rid=self.e.trade(1,2,10,0,[],[],'Рядом')
        self.e.confirm(rid,1);self.e.confirm(rid,2);self.e.approve_request(rid)
        self.assertEqual(self.e.player(2)['wallet'],10010)
    def test_trade_not_across_floors(self):
        self.place(1,'W3');self.place(2,'W10','rooms');self.assertFalse(self.e.map_adjacent(1,2))
    def test_arrivals_get_distinct_cells(self):
        self.assertTrue(self.e.map_adjacent(1,2))
        s=self.e.map_snapshot(1);self.assertEqual(len(s['people']),3)
        self.assertEqual(len({(p['x'],p['y']) for p in s['people']}),3)
    def test_wallet_theft_not_at_distance(self):
        self.e.map_enable(1);self.place(2,'C16');self.e.visit(1)
        with self.assertRaises(RuleError):self.e.rob(1,2,1,'wallet',5,5,0,10)
        self.assertEqual(self.e.player(1)['turn'],1)
    def test_weekly_grants_once_and_no_accumulation(self):
        self.e.db.execute("UPDATE meta SET value='1' WHERE key='map_weekly'")
        self.assertEqual(self.e.map_tick(),3)
        self.move(1,'M16');self.assertEqual(self.e.map_tick(),0)
        self.assertEqual(self.e.map_position(1)['remaining'],5)
        self.today+=timedelta(days=7);self.assertEqual(self.e.map_tick(),3)
        self.assertEqual(self.e.map_position(1)['remaining'],6)
    def test_weekly_ghost_gets_only_movement(self):
        self.e.life(1,True);self.e.db.execute("UPDATE meta SET value='1' WHERE key='map_weekly'");self.e.map_tick()
        self.assertEqual(self.e.player(1)['turn'],0);self.assertEqual(self.e.map_position(1)['remaining'],6)
    def test_weekly_skips_paused_and_missing_speed(self):
        self.e.pause(2,1);self.e.db.execute('UPDATE character_stats SET speed_ft=NULL WHERE uid=3')
        self.e.db.execute("UPDATE meta SET value='1' WHERE key='map_weekly'")
        self.assertEqual(self.e.map_tick(),1)
    def test_manual_movement_grant_does_not_reissue_weekly_action(self):
        self.e.db.execute("UPDATE meta SET value='1' WHERE key='map_weekly'");self.e.map_tick()
        self.request(1,'action',dict(resource='base',text='Ход'))
        self.e.map_grant(1);self.e.map_tick()
        self.assertEqual(self.e.player(1)['turn'],0)

    def test_weekly_blocks_visit_refill(self):
        self.e.db.execute("UPDATE meta SET value='1' WHERE key='map_weekly'");self.e.map_tick()
        with self.assertRaises(RuleError):self.e.visit(1)
    def test_config_unsafe_shape_rejected(self):
        for edit in (lambda d:d.update(cell_ft=10),lambda d:d['floors']['hall'].update(rows=['.','..']),lambda d:d['spawn'].update(cell='A1')):
            d=self.e.map_data();edit(d)
            with self.assertRaises(RuleError):self.e.map_validate(d)
    def test_reload_does_not_erase_positions(self):
        self.place(1,'C16');self.e.map_load();p=self.e.map_position(1)
        self.assertEqual(cell(p['x'],p['y']),'C16')
    def test_private_map_preferred_over_public_repository_layout(self):
        data=self.e.map_data();data['name']='Приватная карта'
        Path(self.tmp.name+'/private-map.json').write_text(json.dumps(data))
        self.e.map_load();self.assertEqual(self.e.map_data()['name'],'Приватная карта')

    def test_rejected_reload_rolls_back_geometry(self):
        data=self.e.map_data();data['floors']['hall']['rows'][15]=data['floors']['hall']['rows'][15][:2]+'#'+data['floors']['hall']['rows'][15][3:]
        self.place(1,'C16');old=self.e.map_data()
        with patch('map_rules.Path.read_text',return_value=json.dumps(data)):
            with self.assertRaises(RuleError):self.e.map_load()
        self.assertEqual(self.e.map_data(),old)
    def test_upgrade_from_pre_map_schema_preserves_existing_game(self):
        item=self.e.add_item(1,'Кольцо');self.e.inspiration(1,1)
        before=self.e.player(1);stats=self.e.char_data(1)
        for table in ('map_orders','map_reveals','map_positions'):self.e.db.execute('DROP TABLE '+table)
        self.e.db.execute("DELETE FROM meta WHERE key LIKE 'map_%'")
        self.e.db.close();self.e=Engine(self.tmp.name+'/test.db',lambda:self.today)
        self.assertEqual(self.e.player(1),before)
        self.assertEqual(self.e.char_data(1),stats)
        self.assertEqual(self.e.db.execute('SELECT owner FROM items WHERE id=?',(item,)).fetchone()[0],1)
        self.assertEqual(self.e.map_position(1)['remaining'],0)
        self.assertFalse(self.e.map_enabled())

    def test_map_state_persisted_after_restart(self):
        self.e.visit(1);self.move(1,'K16');self.e.map_door('kitchen',1);self.e.map_reveal('cellar','B2','C3')
        self.e.backup(self.tmp.name+'/restart.db');other=Engine(self.tmp.name+'/restart.db',lambda:self.today)
        try:
            self.assertEqual(other.map_position(1)['remaining'],5)
            self.assertTrue(other.map_data()['doors']['kitchen']['open'])
            self.assertTrue(other.map_known('cellar',1,1))
        finally:other.db.close()
    def test_png_is_valid_and_reproducible(self):
        snap=self.e.map_snapshot(1);png=render_map(snap)
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertEqual(png,render_map(snap))
        w,h=struct.unpack('!II',png[16:24]);self.assertGreater(w,500)
        offset=8;compressed=b''
        while offset<len(png):
            n=struct.unpack('!I',png[offset:offset+4])[0];kind=png[offset+4:offset+8];payload=png[offset+8:offset+8+n]
            crc=struct.unpack('!I',png[offset+8+n:offset+12+n])[0]
            self.assertEqual(crc,zlib.crc32(kind+payload)&0xffffffff)
            if kind==b'IDAT':compressed+=payload
            offset+=12+n
        self.assertEqual(len(zlib.decompress(compressed)),h*(1+w*3))
    def test_snapshot_does_not_contain_private_stats(self):
        snap=self.e.map_snapshot(1)
        for p in snap['people']:
            self.assertEqual(set(p),{'uid','name','dead','x','y','portrait'})
    def test_100_guests_without_overlap_errors(self):
        for uid in range(4,101):self.e.register(uid,'Гость '+str(uid),'Тест');self.e.approve(uid)
        snap=self.e.map_snapshot(1);self.assertEqual(len(snap['people']),100)
        self.assertTrue(render_map(snap).startswith(b'\x89PNG'))

class MapUI(unittest.TestCase):
    tearDown=support.Rules.tearDown
    def setUp(self):
        support.Rules.setUp(self);self.api=support.FakeAPI();self.photos=[]
        self.api.upload_photo=lambda data,**kw:self.photos.append((data,kw)) or {'message_id':55}
        self.bot=Bot(self.api,self.e,{99},-100,7);self.n=100
    def cmd(self,uid,text,private=True):
        self.n+=1;self.bot.handle(support.Transport.update(self,uid,text,self.n,private))
    def last(self):return [k for m,k in self.api.calls if m=='sendMessage'][-1]
    def test_map_command_queues_private_png(self):
        self.cmd(1,'/map');self.bot.housekeeping()
        self.assertEqual(len(self.photos),1);self.assertEqual(self.photos[0][1]['chat_id'],1)
        self.assertIn('Тестовая схема',self.photos[0][1]['caption'])
    def test_map_command_in_group_does_not_leak_positions(self):
        self.cmd(1,'/map',False);self.assertEqual(len(self.photos),0)
        self.assertIn('личной переписке',self.last()['text'])
    def test_non_master_cannot_change_map(self):
        for cmd in ('/mapgrant 1','/mapplace 1 hall C16','/mapdoor kitchen 1','/mapmode 1','/mapweekly 1','/mapreveal cellar B2 C3','/mapload'):
            self.cmd(1,cmd)
        self.assertFalse(self.e.map_enabled());self.assertEqual(self.e.meta_value('map_weekly'),'0')
        self.assertEqual(self.e.map_position(1)['remaining'],0)
    def test_guided_move_has_confirmation_before_spend(self):
        self.e.visit(1);self.cmd(1,'/ui mapmove hall');self.cmd(1,'K16')
        order=self.e.db.execute('SELECT id FROM map_orders').fetchone()[0]
        self.assertEqual(self.e.map_position(1)['remaining'],6)
        self.cmd(1,f'/ui mappay {order}')
        self.assertEqual(self.e.map_position(1)['remaining'],5)
    def test_no_action_button_without_resource(self):
        self.cmd(1,'/ui actions')
        buttons=str(self.last()['reply_markup'])
        self.assertNotIn('action:base',buttons);self.assertNotIn('action:inspiration',buttons)
        self.cmd(1,'/ui action inspiration');self.assertIsNone(self.bot.ui_state(1))
    def test_main_menu_and_ghost_have_map(self):
        self.cmd(1,'/menu');self.assertIn('Карта',str(self.last()['reply_markup']))
        self.e.life(1,True);self.cmd(1,'/menu');self.assertIn('Карта',str(self.last()['reply_markup']))
    def test_weekly_admin_command_works_without_master_character(self):
        self.cmd(99,'/mapweekly 1');self.assertEqual(self.e.player(1)['turn'],1)
        self.assertEqual(self.e.map_position(1)['remaining'],6)
    def test_map_photo_failure_preserves_move_and_retries(self):
        from bot import TelegramError
        self.e.visit(1);o=self.e.map_prepare(1,'hall','K16');self.cmd(1,f'/ui mappay {o["id"]}')
        self.api.upload_photo=lambda *a,**kw:(_ for _ in ()).throw(TelegramError('test'))
        self.bot.housekeeping();self.assertEqual(self.e.map_position(1)['remaining'],5)
        row=self.e.db.execute("SELECT sent FROM outbox WHERE text LIKE '@MAP@%' ORDER BY id DESC").fetchone()
        self.assertEqual(row[0],0)

if __name__=='__main__':unittest.main()
