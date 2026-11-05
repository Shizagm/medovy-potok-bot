"""Private Telegram photo wizard; uploads never enter the public repository."""
from interface import kb,BACK
from engine import RuleError
from map_rules import cell

class TokenInterfaceMixin:
    def token_menu(self,uid):
        self.e.player(uid)
        self.send(uid,'🟣 ЖЕТОН ПЕРСОНАЖА\n\n'+('Портрет загружен.' if self.e.token_get(uid) else 'Пока используется силуэт.')+'\nПришли портрет после нажатия кнопки. Рой обрежет его в квадрат и покажет круглым жетоном с фиолетовой рамкой. Твой жетон выделен зелёной обводкой.\n\nJPEG/PNG до 5 МБ. Лучше крупный портрет: лицо в центре.',kb([[('🖼 Загрузить портрет','tokenupload')],[('Убрать портрет','tokenclear'),('🗺 Карта','map')],[('🍯 Меню','home')]]))
    def token_dispatch(self,uid,tail):
        a=tail.split();action=a[0] if a else ''
        if action not in ('token','tokenupload','tokenclear','tokenclearconfirm'):return False
        self.e.player(uid)
        if action=='token':self.token_menu(uid)
        elif action=='tokenupload':self.token_prompt(uid,'player',uid)
        elif action=='tokenclear':self.send(uid,'Убрать твой портрет и вернуть силуэт?',kb([[('Да, убрать','tokenclearconfirm'),('Отмена','token')]]))
        else:self.e.token_clear(uid);self.e.notify(uid,'Портрет убран.');self.queue_map(uid)
        return True
    def token_prompt(self,uid,kind,target):
        if kind=='npc':
            self.ui_admin_required(uid)
            if not self.e.db.execute('SELECT 1 FROM map_npcs WHERE id=?',(target,)).fetchone():raise RuleError('Такого НПС нет.')
        else:
            self.e.player(target)
            if target!=uid:self.ui_admin_required(uid)
        self.ui_set(uid,'token_upload',payload={'kind':kind,'target':target})
        self.ui_prompt(uid,'🖼 Пришли портрет одним изображением в эту личную переписку: фотографией или файлом JPEG/PNG до 5 МБ.\nПортрет будет виден всем посетителям на карте. Исходник не сохраняется — только уменьшенная копия.')
    def token_receive(self,uid,msg):
        self.member(uid)
        st=self.ui_state(uid)
        if not st or st['flow']!='token_upload':
            self.send(uid,'Чтобы поставить портрет на жетон, сначала открой /token → «Загрузить портрет».');return
        kind=st['payload']['kind'];target=st['payload']['target']
        if kind=='npc' or target!=uid:self.ui_admin_required(uid)
        else:self.e.player(uid)
        if msg.get('photo'):
            item=msg['photo'][-1]
        else:
            item=msg.get('document',{})
            if item.get('mime_type') not in ('image/png','image/jpeg'):raise RuleError('Нужен файл JPEG/PNG или обычная фотография.')
        from token_rules import MAX_UPLOAD
        if item.get('file_size',0)>MAX_UPLOAD:raise RuleError('Портрет должен быть не больше 5 МБ.')
        raw=self.api.download_image(item['file_id'])
        if kind=='npc':self.e.npc_token_set(target,raw)
        else:self.e.token_set(target,raw)
        self.ui_clear(uid);self.e.notify(uid,'🟣 Портрет сохранён. Новый жетон появится на следующей карте.')
        if kind=='player':self.queue_map(target)
    def token_command(self,uid,cmd,tail):
        if cmd=='/token':self.token_menu(uid);return True
        if cmd=='/enter':self.e.map_enter(uid);self.queue_map(uid);return True
        if cmd not in ('/npc','/npcdel','/npctoken','/npcs','/playertoken'):return False
        self.ui_admin_required(uid)
        if cmd=='/npc':
            numbers,sep,name=tail.partition('|');nid,kind,area,value,size=numbers.split()
            if not sep:raise RuleError('Формат: /npc roy npc hall L5 1 | Рой')
            self.e.map_entity_set(nid,kind,area,value,int(size),name.strip());self.send(uid,'НПС поставлен. Его клетки закрыты для прохода.',BACK)
        elif cmd=='/npcdel':self.e.map_entity_remove(tail.strip());self.send(uid,'НПС убран.',BACK)
        elif cmd=='/npctoken':self.token_prompt(uid,'npc',tail.strip())
        elif cmd=='/playertoken':self.token_prompt(uid,'player',int(tail))
        elif cmd=='/npcs':
            rows=self.e.db.execute('SELECT * FROM map_npcs ORDER BY id').fetchall()
            self.send(uid,'🧙 НПС И МОНСТРЫ\n\n'+('\n'.join(f'{r["id"]}: {r["name"]} · {r["kind"]} · {r["area"]} {cell(r["x"],r["y"])} · {r["size"]}×{r["size"]}' for r in rows) or 'Пока нет.')+'\n\n/npc roy npc hall L5 1 | Рой\n/npc troll monster hall R10 2 | Тролль\n/npctoken roy — загрузить портрет\n/npcdel roy — убрать\n/playertoken ID — портрет другого героя',BACK)
        return True
