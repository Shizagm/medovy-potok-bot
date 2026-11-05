import io,json,sqlite3,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import test_engine as support
from engine import Engine,RuleError
from bot import Bot,Telegram,TelegramError
from map_rules import cell
from map_render import render_map
from token_rules import normalize_portrait,MAX_UPLOAD

def portrait(color='red',size=(100,200),fmt='PNG'):
    out=io.BytesIO();Image.new('RGB',size,color).save(out,format=fmt);return out.getvalue()

class Landing(unittest.TestCase):
    setUp=support.Rules.setUp
    tearDown=support.Rules.tearDown
    def at(self,uid,value):self.e.map_set_position(uid,'hall',value)
    def test_pass_through_player_without_extra_cost(self):
        self.e.visit(1);self.at(2,'K16')
        o=self.e.map_prepare(1,'hall','J16');self.assertEqual(o['cost'],2)
        self.e.map_commit(1,o['id']);self.assertEqual(self.e.map_position(1)['remaining'],4)
    def test_cannot_end_in_occupied_cell(self):
        self.e.visit(1);self.at(2,'K16')
        with self.assertRaises(RuleError):self.e.map_prepare(1,'hall','K16')
        self.assertEqual(self.e.map_position(1)['remaining'],6)
    def test_partial_path_stops_before_occupied_budget_endpoint(self):
        self.e.visit(1);self.at(2,'J16')
        self.e.db.execute('UPDATE map_positions SET remaining=2 WHERE uid=1')
        o=self.e.map_prepare(1,'hall','G16')
        self.assertEqual((o['destination'][1:],o['cost']),((10,15),1))
    def test_not_enough_to_cross_occupied_cell_leaves_position(self):
        self.e.visit(1);self.at(2,'K16');self.e.db.execute('UPDATE map_positions SET remaining=1 WHERE uid=1')
        with self.assertRaises(RuleError):self.e.map_prepare(1,'hall','J16')
        self.assertEqual(self.e.map_position(1)['remaining'],1)
    def test_other_guest_can_take_destination_before_confirm(self):
        self.e.visit(1);self.at(2,'M16');o=self.e.map_prepare(1,'hall','K16');self.at(2,'K16')
        with self.assertRaises(RuleError):self.e.map_commit(1,o['id'])
        self.assertEqual(self.e.map_position(1)['remaining'],6)
    def test_two_guests_race_one_destination_only_one_lands(self):
        self.e.visit(1);self.e.visit(2);self.at(2,'J16')
        a=self.e.map_prepare(1,'hall','K16');b=self.e.map_prepare(2,'hall','K16')
        self.e.map_commit(1,a['id'])
        with self.assertRaises(RuleError):self.e.map_commit(2,b['id'])
        self.assertEqual(self.e.map_position(2)['remaining'],6)
    def test_master_cannot_overlap_guests(self):
        self.at(1,'L16')
        with self.assertRaises(RuleError):self.at(2,'L16')
    def test_database_prevents_overlapping_active_positions(self):
        self.at(1,'L16');self.at(2,'K16')
        with self.assertRaises(sqlite3.IntegrityError):self.e.db.execute('UPDATE map_positions SET x=11,y=15 WHERE uid=2')
    def test_ghost_cannot_finish_in_another_character(self):
        self.e.life(1,True);self.e.map_grant(1);self.at(1,'L16');self.at(2,'K16')
        with self.assertRaises(RuleError):self.e.map_prepare(1,'hall','K16')
        o=self.e.map_prepare(1,'hall','J16');self.assertEqual(o['cost'],2)
    def test_full_floor_waits_off_map_and_can_enter_after_space_opens(self):
        data=self.e.map_data();data.update(spawn={'area':'hall','cell':'A1'},floors={'hall':{'name':'Малый зал','rows':['..']}},doors={},links=[],landmarks={})
        self.e.map_save(data)
        p1=self.e.map_position(1);p2=self.e.map_position(2);p3=self.e.map_position(3)
        self.assertTrue(p1['on_map']);self.assertTrue(p2['on_map']);self.assertFalse(p3['on_map'])
        self.e.map_grant(3)
        with self.assertRaises(RuleError):self.e.map_prepare(3,'hall','B1')
        with self.assertRaises(RuleError):self.e.map_enter(3)
        self.e.db.execute('UPDATE map_positions SET on_map=0 WHERE uid=2')
        self.assertTrue(self.e.map_enter(3)['on_map'])
    def test_v08_overlaps_migrate_without_gold_or_movement_loss(self):
        for uid in (1,2,3):self.e.map_position(uid)
        self.e.db.execute('DROP INDEX map_single_occupancy')
        self.e.db.execute("UPDATE map_positions SET area='hall',x=11,y=15,remaining=4,on_map=1")
        self.e.db.execute("DELETE FROM meta WHERE key='map_occupancy_v9'")
        self.e.map_migrate_occupancy()
        rows=self.e.db.execute('SELECT * FROM map_positions').fetchall()
        self.assertEqual(len({(r['area'],r['x'],r['y']) for r in rows}),3)
        self.assertTrue(all(r['remaining']==4 and r['on_map'] for r in rows))
        self.assertEqual(self.e.player(1)['wallet'],10000)
    def test_migration_is_not_repeated_after_restart(self):
        self.at(1,'C16');self.e.map_migrate_occupancy();p=self.e.map_position(1)
        self.assertEqual(cell(p['x'],p['y']),'C16')

class NPCs(unittest.TestCase):
    setUp=support.Rules.setUp
    tearDown=support.Rules.tearDown
    def npc(self,nid='roy',value='K16',size=1,kind='npc'):self.e.map_entity_set(nid,kind,'hall',value,size,'Персонаж')
    def test_npc_blocks_direct_passage_and_path_goes_around(self):
        self.e.visit(1);self.npc();o=self.e.map_prepare(1,'hall','J16')
        self.assertNotIn(('hall',10,15),o['path'])
        self.assertGreater(o['cost'],2)
    def test_npc_blocks_ghost_cell_too(self):
        self.e.life(1,True);self.e.map_grant(1);self.npc()
        with self.assertRaises(RuleError):self.e.map_prepare(1,'hall','K16')
    def test_monster_two_by_two_blocks_all_four_cells(self):
        self.npc('troll','R10',2,'monster');blocked=self.e.map_npc_cells()
        self.assertTrue({('hall',17,9),('hall',18,9),('hall',17,10),('hall',18,10)}<=blocked)
        for n in blocked:self.assertFalse(self.e.map_passable(n))
    def test_cannot_place_npc_over_guest(self):
        self.e.map_position(1)
        with self.assertRaises(RuleError):self.npc('roy','L16')
    def test_npcs_cannot_overlap_each_other(self):
        self.npc('troll','R10',2,'monster')
        with self.assertRaises(RuleError):self.npc('other','S11')
    def test_npc_cannot_overlap_wall_or_outside(self):
        for value in ('A1','Z17','K10'):
            with self.assertRaises(RuleError):self.npc('roy',value,2)
    def test_npc_under_fog_does_not_leak_in_snapshot(self):
        self.e.map_entity_set('secret','monster','cellar','B2',1,'Секрет')
        self.assertEqual(self.e.map_snapshot(1,'cellar')['npcs'],[])
        self.e.map_reveal('cellar','B2','C3');self.assertEqual(self.e.map_snapshot(1,'cellar')['npcs'][0]['name'],'Секрет')
    def test_npc_removal_reopens_cell_and_invalidates_old_routes(self):
        self.e.visit(1);self.npc();o=self.e.map_prepare(1,'hall','M16');self.e.map_entity_remove('roy')
        self.assertTrue(self.e.map_passable(('hall',10,15)))
        with self.assertRaises(RuleError):self.e.map_commit(1,o['id'])
    def test_roy_gets_existing_roy_portrait(self):
        self.npc();self.assertIsNotNone(self.e.db.execute("SELECT png FROM map_npcs WHERE id='roy'").fetchone()[0])
    def test_reloading_map_cannot_wall_off_npc(self):
        self.npc('guard','C16');d=self.e.map_data();rows=list(map(list,d['floors']['hall']['rows']));rows[15][2]='#';d['floors']['hall']['rows']=[''.join(r) for r in rows]
        old=self.e.map_data()
        with patch('map_rules.Path.read_text',return_value=json.dumps(d)):
            with self.assertRaises(RuleError):self.e.map_load()
        self.assertEqual(self.e.map_data(),old)

class Portraits(unittest.TestCase):
    setUp=support.Rules.setUp
    tearDown=support.Rules.tearDown
    def test_portrait_normalized_to_small_square(self):
        raw=portrait(fmt='JPEG');png=self.e.token_set(1,raw)
        im=Image.open(io.BytesIO(png));self.assertEqual(im.size,(128,128));self.assertEqual(im.format,'PNG')
        self.assertEqual(self.e.token_get(1),png)
    def test_corrupted_image_keeps_previous_portrait(self):
        self.e.token_set(1,portrait());before=self.e.token_get(1)
        with self.assertRaises(RuleError):self.e.token_set(1,b'not an image')
        self.assertEqual(self.e.token_get(1),before)
    def test_oversized_bytes_rejected_before_decode(self):
        with self.assertRaises(ValueError):normalize_portrait(b'x'*(MAX_UPLOAD+1))
    def test_large_pixel_image_rejected(self):
        raw=portrait(size=(4000,3100))
        with self.assertRaises(ValueError):normalize_portrait(raw)
    def test_gif_not_accepted_as_png(self):
        with self.assertRaises(ValueError):normalize_portrait(portrait(fmt='GIF'))
    def test_animation_rejected(self):
        out=io.BytesIO();a=Image.new('RGB',(16,16),'red');b=Image.new('RGB',(16,16),'blue');a.save(out,format='PNG',save_all=True,append_images=[b],duration=100,loop=0)
        with self.assertRaises(ValueError):normalize_portrait(out.getvalue())
    def test_transparency_is_composited(self):
        out=io.BytesIO();Image.new('RGBA',(12,12),(255,0,0,0)).save(out,format='PNG')
        png=normalize_portrait(out.getvalue());self.assertEqual(Image.open(io.BytesIO(png)).getpixel((64,64)),(62,46,75))
    def test_metadata_not_preserved(self):
        from PIL.PngImagePlugin import PngInfo
        info=PngInfo();info.add_text('secret','metadata');out=io.BytesIO();Image.new('RGB',(16,16)).save(out,format='PNG',pnginfo=info)
        im=Image.open(io.BytesIO(normalize_portrait(out.getvalue())));self.assertNotIn('secret',im.info)
    def test_removal_only_changes_target(self):
        self.e.token_set(1,portrait());self.e.token_set(2,portrait('blue'));self.e.token_clear(1)
        self.assertIsNone(self.e.token_get(1));self.assertIsNotNone(self.e.token_get(2))
    def test_token_draws_portrait_inside_circle(self):
        self.e.token_set(1,portrait('red'));snap=self.e.map_snapshot(1);png=render_map(snap)
        im=Image.open(io.BytesIO(png));p=snap['viewer'];cx=48+p['x']*48+24;cy=48+p['y']*48+24
        self.assertEqual(im.getpixel((cx,cy)),(255,0,0))
        self.assertNotEqual(im.getpixel((48+p['x']*48,48+p['y']*48)),(255,0,0))
    def test_ghost_retains_distinct_grayscale_portrait(self):
        self.e.token_set(1,portrait('red'));live=render_map(self.e.map_snapshot(1));self.e.life(1,True);ghost=render_map(self.e.map_snapshot(1))
        self.assertNotEqual(live,ghost)
    def test_token_and_npc_survive_backup_and_restart(self):
        self.e.token_set(1,portrait());self.e.map_entity_set('guard','npc','hall','U15',1,'Страж');self.e.npc_token_set('guard',portrait('blue'))
        self.e.backup(self.tmp.name+'/copy.db');other=Engine(self.tmp.name+'/copy.db',lambda:self.today)
        try:
            self.assertEqual(other.token_get(1),self.e.token_get(1))
            self.assertIsNotNone(other.db.execute("SELECT png FROM map_npcs WHERE id='guard'").fetchone()[0])
        finally:other.db.close()

class TokenUI(unittest.TestCase):
    tearDown=support.Rules.tearDown
    def setUp(self):
        support.Rules.setUp(self);self.api=support.FakeAPI();self.api.download_image=lambda f:portrait()
        self.bot=Bot(self.api,self.e,{99},-100,7);self.n=500
    def cmd(self,uid,text,private=True):
        self.n+=1;self.bot.handle(support.Transport.update(self,uid,text,self.n,private))
    def upload(self,uid,photo=True,private=True,size=100,mime='image/png'):
        self.n+=1;msg={'from':{'id':uid},'chat':{'id':uid if private else -100,'type':'private' if private else 'supergroup'}}
        if photo:msg['photo']=[{'file_id':'image','file_size':size}]
        else:msg['document']={'file_id':'image','file_size':size,'mime_type':mime}
        self.bot.handle({'update_id':self.n,'message':msg})
    def test_photo_wizard_saves_only_sender(self):
        self.cmd(1,'/ui tokenupload');self.upload(1)
        self.assertIsNotNone(self.e.token_get(1));self.assertIsNone(self.e.token_get(2));self.assertIsNone(self.bot.ui_state(1))
    def test_document_png_accepted(self):
        self.cmd(1,'/ui tokenupload');self.upload(1,False);self.assertIsNotNone(self.e.token_get(1))
    def test_photo_without_wizard_not_saved(self):
        self.upload(1);self.assertIsNone(self.e.token_get(1))
    def test_group_photo_not_saved(self):
        self.cmd(1,'/ui tokenupload');self.upload(1,private=False);self.assertIsNone(self.e.token_get(1))
    def test_oversize_not_downloaded(self):
        self.cmd(1,'/ui tokenupload');self.api.download_image=lambda f:(_ for _ in ()).throw(AssertionError('download'))
        self.upload(1,size=MAX_UPLOAD+1);self.assertIsNone(self.e.token_get(1))
    def test_non_image_document_not_downloaded(self):
        self.cmd(1,'/ui tokenupload');self.api.download_image=lambda f:(_ for _ in ()).throw(AssertionError('download'))
        self.upload(1,False,mime='application/pdf');self.assertIsNone(self.e.token_get(1))
    def test_cancel_upload_does_not_replace_existing(self):
        old=self.e.token_set(1,portrait('blue'));self.cmd(1,'/ui tokenupload');self.cmd(1,'/ui cancel');self.upload(1)
        self.assertEqual(self.e.token_get(1),old)
    def test_master_can_upload_for_player(self):
        self.cmd(99,'/playertoken 2');self.upload(99)
        self.assertIsNotNone(self.e.token_get(2));self.assertIsNone(self.e.token_get(1))
    def test_player_cannot_upload_for_another(self):
        self.cmd(1,'/playertoken 2');self.upload(1)
        self.assertIsNone(self.e.token_get(2))
    def test_master_can_set_and_remove_npc(self):
        self.cmd(99,'/npc guard npc hall U15 1 | Страж');self.cmd(99,'/npctoken guard');self.upload(99)
        self.assertIsNotNone(self.e.db.execute("SELECT png FROM map_npcs WHERE id='guard'").fetchone()[0])
        self.cmd(99,'/npcdel guard');self.assertIsNone(self.e.db.execute("SELECT 1 FROM map_npcs WHERE id='guard'").fetchone())
    def test_player_cannot_place_monster(self):
        self.cmd(1,'/npc troll monster hall R10 2 | Тролль')
        self.assertIsNone(self.e.db.execute("SELECT 1 FROM map_npcs WHERE id='troll'").fetchone())
    def test_landmark_button_stops_near_roy_instead_of_inside_him(self):
        self.e.map_entity_set('roy','npc','hall','L5',1,'Рой');self.e.map_grant(1)
        self.cmd(1,'/ui mapgoal roy');r=self.e.db.execute('SELECT * FROM map_orders').fetchone()
        self.assertIsNotNone(r);self.assertNotEqual((r['x'],r['y']),(11,4))
    def test_token_menu_in_profile(self):
        self.cmd(1,'/profile')
        text=str([k for m,k in self.api.calls if m=='sendMessage'][-1]['reply_markup']);self.assertIn('Портрет жетона',text)

class Download(unittest.TestCase):
    def test_path_traversal_rejected_without_request(self):
        api=Telegram('123:fake');api.call=lambda *a,**kw:{'file_path':'../secret'}
        with patch('bot.urllib.request.urlopen') as request:
            with self.assertRaises(TelegramError):api.download_image('id')
            request.assert_not_called()
    def test_size_checked_before_fetch(self):
        api=Telegram('123:fake');api.call=lambda *a,**kw:{'file_path':'photos/a.jpg','file_size':MAX_UPLOAD+1}
        with patch('bot.urllib.request.urlopen') as request:
            with self.assertRaises(RuleError):api.download_image('id')
            request.assert_not_called()
    def test_download_timeout_never_exposes_token(self):
        api=Telegram('123:fake');api.call=lambda *a,**kw:{'file_path':'photos/a.jpg'}
        with patch('bot.urllib.request.urlopen',side_effect=TimeoutError()):
            with self.assertRaises(TelegramError) as exc:api.download_image('id')
        self.assertNotIn('fake',str(exc.exception))

if __name__=='__main__':unittest.main()
