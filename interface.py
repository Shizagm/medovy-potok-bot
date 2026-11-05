"""Tavern-themed Telegram menus and private guided input; no CSS/client changes."""
import json
import time
from engine import RuleError,ROOMS

def money(n):return f'{n:,}'.replace(',',' ')
def kb(rows):return {'inline_keyboard':[[{'text':label,'callback_data':'ui:'+action} for label,action in row] for row in rows]}
BACK=kb([[('🍯 К стойке Роя','home')]])

class InterfaceMixin:
    def interface_schema(self):
        self.e.db.execute('CREATE TABLE IF NOT EXISTS ui_sessions(uid INTEGER PRIMARY KEY,flow TEXT NOT NULL,step INTEGER NOT NULL,payload TEXT NOT NULL,updated INTEGER NOT NULL)')

    def ui_state(self,uid):
        row=self.e.db.execute('SELECT * FROM ui_sessions WHERE uid=?',(uid,)).fetchone()
        if not row:return None
        if int(time.time())-row['updated']>1800:
            self.e.db.execute('DELETE FROM ui_sessions WHERE uid=?',(uid,));return None
        r=dict(row);r['payload']=json.loads(r['payload']);return r

    def ui_set(self,uid,flow,step=0,payload=None):
        self.e.db.execute('INSERT OR REPLACE INTO ui_sessions VALUES(?,?,?,?,?)',(uid,flow,step,json.dumps(payload or {},ensure_ascii=False),int(time.time())))

    def ui_clear(self,uid):self.e.db.execute('DELETE FROM ui_sessions WHERE uid=?',(uid,))

    def ui_prompt(self,uid,text):
        self.send(uid,text,kb([[('Отменить ввод','cancel')]]))

    def ui_home(self,uid):
        self.ui_clear(uid)
        try:p=self.e.player(uid,False)
        except RuleError:p=None
        if not p:
            rows=[[('📖 Записаться в книгу гостей','register')],[('📜 Как здесь всё устроено','rules')]]
            if uid in self.admins:rows.append([('🗝 Стойка мастера','admin')])
            self.send(uid,'🍯 МЕДОВЫЙ ПОТОК\nТаверна между мирами\n\nЗаходи. Я Рой, хозяин этого места.\nПрежде чем осваиваться, запишем твоего героя в книгу гостей.',kb(rows));return
        if not p['approved']:
            rows=[[('📜 Правила таверны','rules')]]
            if uid in self.admins:rows.append([('🗝 Стойка мастера','admin')])
            self.send(uid,f'🍯 КНИГА ГОСТЕЙ\n\n{p["name"]}, твоя запись ждёт подтверждения мастера.\nКак только он её одобрит, открою меню таверны.',kb(rows));return
        if p['dead']:
            rows=[[('👤 Мой герой','hero'),('🕯 Выкупить себя','resoffer:'+str(uid))],[('🪙 Посмотреть золото','wallet'),('📖 Правила','rules')],[('📚 Мои сведения','dossiers'),('🗺 Карта','map')]]
            if uid in self.admins:rows.append([('🗝 Стойка мастера','admin')])
            self.send(uid,f'🕯 МЕДОВЫЙ ПОТОК\n{p["name"]} · призрак\n\nПока доступны полёт и общение. Переверни жетон обратной стороной.\nВернуться к жизни можно за 1000 зм у Шизы.',kb(rows));return
        total=p['wallet']+p['chest']+p['custody']+self.ui_escrow(uid)
        rows=[[('👤 Мой герой','hero'),('🪙 Кошелёк','wallet')],[('📜 Доска Роя','board'),('🎲 Покер на костях','poker')],[('🏆 Рейтинги','ratings'),('🗝 Моё место','house')],[('🖐 Сделать ход','actions'),('📨 Мои заявки','requests')],[('🤝 Сделка','trade'),('📖 Правила','rules')]]
        rows.append([('🗺 Карта и передвижение','map')])
        rows.append([('🎁 Лавка Роя','shop'),('🍯 Кошелёк Роя','roy')])
        rows.append([('🔎 Сведения о героях','charlist'),('🕯 Выкуп у Шизы','resmenu')])
        if self.e.meta_value('support_enabled','0')=='1':rows.append([('🔥 Поддержка «Феникса»','support')])
        if uid in self.admins:rows.append([('⚙ Стойка мастера','admin')])
        self.send(uid,f'🍯 МЕДОВЫЙ ПОТОК\nТаверна между мирами\n\nС возвращением, {p["name"]}.\nЧем займёмся?\n\n🪙 Золото: {money(total)} зм\n✨ Вдохновение: '+('есть' if p['inspiration'] else 'пока нет'),kb(rows))

    def ui_escrow(self,uid):
        return self.e.db.execute("SELECT COALESCE(SUM(stake),0) FROM poker WHERE status IN ('active','showdown') AND (a=? OR b=?)",(uid,uid)).fetchone()[0]

    def ui_hero(self,uid):
        p=self.e.player(uid)
        text=f'👤 {p["name"]}\nОтряд: {p["party"]}\n\n'
        text+='🕯 На кладбище\n' if p['dead'] else '🟢 Жив\n'
        if p['paused']:text+='⏸ Участие приостановлено мастером\n'
        text+='✨ Вдохновение Роя: '+('есть — одно дополнительное действие' if p['inspiration'] else 'нет')+'\n'
        text+='🖐 Основное действие: '+('доступно' if p['turn'] else 'сейчас нет')+'\n'
        text+='🎯 Дополнительное за визит: '+('уже использовано' if p['extra_used'] else 'ещё не использовано')+'\n'
        text+='\n🗝 '+ROOMS[p['tier']][0]+'\n'
        items=self.e.db.execute('SELECT id,name FROM items WHERE owner=? ORDER BY id',(uid,)).fetchall()
        text+='\n🎒 Предметы\n'+('\n'.join(f'• {r["name"]} · №{r["id"]}' for r in items) or 'Пока ничего не записано.')
        self.send(uid,text,kb([[('🖐 Сделать ход','actions'),('🪙 Кошелёк','wallet')],[('🎲 Покер','poker'),('Данные профиля','details')],[('🍯 К стойке Роя','home')]]))

    def ui_wallet(self,uid):
        p=self.e.player(uid);held,_=self.e._held(uid);escrow=self.ui_escrow(uid)
        text=f'🪙 КОШЕЛЁК {p["name"]}\n\nПри себе: {money(p["wallet"])} зм\nВ сундуке: {money(p["chest"])} зм\nНа хранении у Роя: {money(p["custody"])} зм\nВ банке покера: {money(escrow)} зм\n\nВсего: {money(p["wallet"]+p["chest"]+p["custody"]+escrow)} зм\nЗарезервировано для сделок: {money(held)} зм\n\nРасходы на постой: {ROOMS[p["tier"]][1]} зм/день'+(' · питание не начисляется' if p['dead'] else ' + 1 зм/день питание')
        self.send(uid,text,kb([[('📥 В сундук','storage:in'),('📤 Из сундука','storage:out')],[('🍺 Угостить / потратить','spend'),('📒 История','history')],[('🤝 Сделка','trade'),('🍯 Меню','home')]]))

    def ui_admin_required(self,uid):
        if uid not in self.admins:raise RuleError('Эта часть стойки — для мастера.')

    def ui_admin(self,uid):
        self.ui_admin_required(uid);self.ui_clear(uid)
        self.send(uid,'🗝 СТОЙКА МАСТЕРА\n\nИгрокам сюда не заглядывать.\nЗаявки, награды и книга гостей — всё под рукой.',kb([[('👥 Гости','adminplayers'),('📨 Все заявки','adminpending')],[('🪙 Изменить золото','select:gold'),('✨ Вдохновение','select:inspire')],[('🖐 Выдать ход','select:visit'),('📜 Изменить доску','boardedit')],[('🎁 Лавка, Рой и копилка','features')],[('🗺 Настройки карты','mapadmin'),('💾 Создать копию','backup')],[('📚 Все команды','commands')],[('🍯 К стойке Роя','home')]]))

    def ui_dispatch(self,uid,tail):
        if self.token_dispatch(uid,tail):return
        if self.map_dispatch(uid,tail):return
        if self.character_ui(uid,tail):return
        if self.feature_ui(uid,tail):return
        args=tail.split();action=args[0] if args else 'home'
        if action=='mapadmin':self.map_command(uid,'/mapadmin','');return
        if action=='cancel':self.ui_clear(uid);self.ui_home(uid);return
        if action=='home':self.ui_home(uid);return
        if action=='rules':
            self.send(uid,'📖 ПРАВИЛА «МЕДОВОГО ПОТОКА»\n\n• За посещение мастер выдаёт один ход: передвижение и одно действие.\n• Вдохновение Роя даёт дополнительное действие после основного. Хранится максимум одно.\n• Сначала заяви действие. Проверку назначает мастер; повторного броска нет.\n• Сделку подтверждают оба участника и мастер после проверки карты.\n• Покер проходит самостоятельно. До двух перебросов, затем фиксация рук и общее вскрытие.\n• Постой и питание оплачиваются по календарным дням.\n• Карточка закрыта: заполнение и изменения подтверждает мастер. Сведения Роя о другом герое стоят 500 зм за снимок.\n• Скрытность должна быть строго выше пассивного Восприятия жертвы: при 12 нужно 13+.\n• Призрак только летает и общается. Действия, торговля и покер закрыты.\n• Выкуп у Шизы — 1000 зм: платишь сам за себя или живой герой за тебя.\n• После выкупа штраф −4 к проверкам; каждые 7 дней на 1 меньше. Повторный выкуп снова даёт −4.\n\nПодробности событий и поручения ищи на доске Роя.',BACK);return
        if action=='register':
            try:self.e.player(uid,False)
            except RuleError:
                self.ui_set(uid,'register');self.ui_prompt(uid,'📖 КНИГА ГОСТЕЙ\n\nКак зовут твоего персонажа? Напиши имя одним сообщением.');return
            raise RuleError('Ты уже записан в книгу гостей.')
        # Master may not have a playable character, so admin routes precede player checks.
        if action in ('admin','commands','adminplayers','adminpending','select','agoldmenu','agold','ainspire','avisit','boardedit','backup','confirm'):
            self.ui_admin_required(uid)
            if action=='admin':self.ui_admin(uid);return
            if action=='commands':self.send(uid,self.admin_help,kb([[('🗝 Меню мастера','admin')]]));return
            if action=='adminplayers':
                rows=self.e.db.execute('SELECT uid,name,approved FROM players ORDER BY name').fetchall()
                buttons=[[(('🟢 ' if r['approved'] else '⏳ ')+r['name'],f'adminplayer:{r["uid"]}')] for r in rows]
                buttons.append([('🗝 Назад','admin')])
                self.send(uid,'👥 КНИГА ГОСТЕЙ\nВыбери героя.',kb(buttons));return
            if action=='adminpending':
                rows=self.e.db.execute("SELECT id,kind,a FROM requests WHERE status='pending' ORDER BY id LIMIT 30").fetchall()
                buttons=[[(f'№{r["id"]} · {self.e.player(r["a"],False)["name"]}',f'request:{r["id"]}')] for r in rows]
                buttons.append([('🗝 Назад','admin')])
                self.send(uid,'📨 ЖДУТ РЕШЕНИЯ\n'+('Выбери заявку.' if rows else 'Пока всё разобрано.'),kb(buttons));return
            if action=='select':
                mode=args[1]
                if mode not in ('gold','inspire','visit'):raise RuleError('Неизвестное действие.')
                rows=self.e.db.execute('SELECT uid,name FROM players WHERE approved=1 ORDER BY name').fetchall()
                buttons=[]
                for r in rows:
                    target=f'agoldmenu:{r["uid"]}' if mode=='gold' else f'inspiremenu:{r["uid"]}' if mode=='inspire' else f'avisit:{r["uid"]}'
                    buttons.append([(r['name'],target)])
                buttons.append([('🗝 Назад','admin')]);self.send(uid,'Выбери героя.',kb(buttons));return
            if action=='agoldmenu':
                who=int(args[1]);p=self.e.player(who)
                self.send(uid,f'🪙 {p["name"]}\nКошелёк: {money(p["wallet"])} зм\n\nКак изменить учёт?',kb([[('Начислить доход',f'agold:{who}:income'),('Записать расход',f'agold:{who}:expense')],[('Установить кошелёк',f'agold:{who}:set')],[('🗝 Назад','admin')]]));return
            if action=='agold':
                who=int(args[1]);mode=args[2];p=self.e.player(who)
                if mode not in ('income','expense','set'):raise RuleError('Неверный вид операции.')
                self.ui_set(uid,'admin_gold',payload={'who':who,'mode':mode})
                label={'income':'Сколько начислить в доход','expense':'Сколько списать в расход','set':'Какой точный остаток установить в кошельке'}[mode]
                self.ui_prompt(uid,f'🪙 {p["name"]}\n{label}?\nНапиши целое число золотых.');return
            if action=='ainspire':
                self.e.inspiration(int(args[1]),int(args[2]));self.send(uid,'✨ Запись о Вдохновении обновлена.',kb([[('🗝 Меню мастера','admin')]]));return
            if action=='avisit':
                who=int(args[1]);self.e.visit(who);self.send(uid,'🖐 Ход выдан: '+self.e.player(who)['name'],kb([[('🗝 Меню мастера','admin')]]));return
            if action=='boardedit':self.ui_set(uid,'board');self.ui_prompt(uid,'📜 ДОСКА РОЯ\n\nПришли текст поручений одним сообщением (до 3500 символов). Игроки увидят его по кнопке «Доска Роя».');return
            if action=='backup':
                self.e.db.execute("INSERT OR REPLACE INTO meta VALUES('backup_requested','1')");self.send(uid,'💾 Рой готовит копию книги. Подтверждение придёт отдельно.',kb([[('🗝 Меню мастера','admin')]]));return
            if action=='confirm':
                st=self.ui_state(uid)
                if not st or st['flow']!='admin_confirm':raise RuleError('Эта запись уже исполнена или отменена.')
                if len(args)!=2 or args[1]!=st['payload']['nonce']:raise RuleError('Это старое подтверждение.')
                p=st['payload'];amount=p['amount']
                self.e.adjust(p['who'],-amount if p['mode']=='expense' else amount,p['reason'],'set' if p['mode']=='set' else 'delta',p['mode']=='income',p['mode']=='expense')
                self.ui_clear(uid);self.send(uid,'🪙 Готово. Рой внёс запись в книгу.',kb([[('🗝 Меню мастера','admin')]]));return
        if action in ('adminplayer','admit','inspiremenu'):
            self.ui_admin_required(uid);who=int(args[1]);p=self.e.player(who,False)
            if action=='admit':self.e.approve(who);self.send(uid,'📖 Гость допущен в таверну.',kb([[('👥 Книга гостей','adminplayers')]]));return
            if action=='inspiremenu':
                self.send(uid,f'✨ {p["name"]}\nВдохновение: '+('есть' if p['inspiration'] else 'нет'),kb([[('Выдать',f'ainspire:{who}:1'),('Снять',f'ainspire:{who}:0')],[('🗝 Назад','admin')]]));return
            rows=[[('🪙 Золото',f'agoldmenu:{who}'),('✨ Вдохновение',f'inspiremenu:{who}')],[('🖐 Выдать ход',f'avisit:{who}')],[('📝 Карточка',f'charadmin:{who}'),('❤️ Здоровье',f'hpedit:{who}')]] if p['approved'] else [[('📖 Одобрить гостя',f'admit:{who}')]]
            rows.append([('👥 Назад','adminplayers')]);self.send(uid,f'👤 {p["name"]}\nОтряд: {p["party"]}\nID: {who}\n'+('Допущен' if p['approved'] else 'Ждёт допуска'),kb(rows));return
        self.e.player(uid)
        if action in ('actions','action','storage','spend','trade','partner','rent'):self.e.require_alive(uid)
        if action=='hero':self.ui_hero(uid);return
        if action=='wallet':self.ui_wallet(uid);return
        if action=='details':self.send(uid,self.profile(uid),BACK);return
        if action=='board':
            row=self.e.db.execute("SELECT value FROM meta WHERE key='quest_board'").fetchone()
            text=row[0] if row else 'Пока новых поручений нет. Загляни позже — вывешу, как появится работа.'
            self.send(uid,'📜 ДОСКА РОЯ\n\n'+text,BACK);return
        if action=='house':
            p=self.e.player(uid);rate=ROOMS[p['tier']][1]
            text=f'🗝 МОЁ МЕСТО\n\nСейчас: {ROOMS[p["tier"]][0]}\nАренда: {rate} зм в день\nСундук: {money(p["chest"])}/{money(ROOMS[p["tier"]][2])} зм\n\nВыбор места подтверждает мастер по карте.'
            self.send(uid,text,kb([[('Койка · 20 зм/день','rent:1')],[('Комната · 50 зм/день','rent:2')],[('Большая · 100 зм/день','rent:3')],[('Освободить место','rent:0'),('🍯 Меню','home')]]));return
        if action=='rent':
            tier=int(args[1])
            if tier not in ROOMS:raise RuleError('Неизвестное жильё.')
            self.new_request(self.e.request(uid,'rent',{'tier':tier}));return
        if action=='actions':
            p=self.e.player(uid);rows=[]
            if p['turn']:rows.append([('Основное действие','action:base')])
            if p['inspiration'] and not p['extra_used'] and p['visit'] and not p['turn']:rows.append([('✨ Вдохновение Роя','action:inspiration')])
            rows.append([('🗺 Передвижение','map'),('🍯 Меню','home')])
            text='🖐 ТВОЙ ХОД\n\n'+('Выбери доступное действие.' if len(rows)>1 else 'Сейчас нет доступного действия. Передвижение учитывается отдельно. Новый ход выдаёт мастер или недельный режим.')
            self.send(uid,text,kb(rows));return
        if action=='action':
            resource=args[1]
            self.e.action_available(uid,resource)
            self.ui_set(uid,'action',payload={'resource':resource});self.ui_prompt(uid,'🖐 Что делает твой герой?\n\nОпиши действие одним сообщением.');return
        if action=='storage':
            if args[1] not in ('in','out'):raise RuleError('Неизвестное направление.')
            self.ui_set(uid,'storage',payload={'direction':args[1]});self.ui_prompt(uid,'🪙 Сколько золотых '+('положить в сундук?' if args[1]=='in' else 'забрать из сундука?')+'\nПеренос подтверждает мастер у карты.');return
        if action=='spend':self.ui_set(uid,'spend');self.ui_prompt(uid,'🍺 Сколько золотых хочешь потратить?');return
        if action=='trade':
            self.e.require_alive(uid)
            page=int(args[1]) if len(args)>1 else 0
            if page<0:raise RuleError('Неверная страница.')
            rows=self.e.db.execute('SELECT uid,name FROM players WHERE approved=1 AND dead=0 AND paused=0 AND uid!=? ORDER BY name',(uid,)).fetchall()
            rows=[r for r in rows if not self.e.map_enabled() or self.e.map_adjacent(uid,r['uid'])]
            buttons=[[(r['name'],f'partner:{r["uid"]}')] for r in rows[page*12:page*12+12]]
            nav=[]
            if page:nav.append(('←',f'trade:{page-1}'))
            if len(rows)>(page+1)*12:nav.append(('→',f'trade:{page+1}'))
            if nav:buttons.append(nav)
            buttons.append([('🗺 Карта','map'),('🍯 Меню','home')])
            self.send(uid,'🤝 СДЕЛКА\n\n'+('С кем договариваемся?' if rows else 'Рядом нет живых доступных партнёров. Подойди по карте.'),kb(buttons));return
        if action=='partner':
            other=int(args[1]);self.e.player(other)
            if other==uid:raise RuleError('Выбери другого героя.')
            self.e.map_trade_check(uid,other)
            self.ui_set(uid,'trade',payload={'other':other});self.ui_prompt(uid,'🤝 Сколько золота отдаёшь ты?\nЕсли только предмет — напиши 0.');return
        if action=='requests':
            rows=self.e.db.execute("SELECT id FROM requests WHERE status='pending' AND (a=? OR b=?) ORDER BY id DESC LIMIT 20",(uid,uid)).fetchall()
            buttons=[[(f'📨 Заявка №{r["id"]}',f'request:{r["id"]}')] for r in rows]+[[('🍯 Меню','home')]]
            self.send(uid,'📨 МОИ ЗАЯВКИ\n\n'+('Выбери запись.' if rows else 'Сейчас нет заявок, ожидающих решения.'),kb(buttons));return
        raise RuleError('Неизвестная кнопка. Открой /menu.')

    def ui_answer(self,uid,text):
        st=self.ui_state(uid)
        if not st:raise RuleError('Ввод завершён или истёк. Открой /menu.')
        flow,step,p=st['flow'],st['step'],st['payload'];text=text.strip()
        if not text or len(text)>3500:raise RuleError('Нужен текст от 1 до 3500 символов.')
        if self.map_answer(uid,text,st):return
        if self.character_answer(uid,text,st):return
        if self.feature_answer(uid,text,st):return
        def amount(zero=False):
            try:n=int(text.replace(' ',''))
            except ValueError:raise RuleError('Напиши целое число золотых, без «зм».')
            if n<(0 if zero else 1) or n>1000000000:raise RuleError('Проверь сумму золотых.')
            return n
        if flow=='register':
            if step==0:
                if len(text)>60:raise RuleError('Имя — до 60 символов.')
                self.ui_set(uid,flow,1,{'name':text});self.ui_prompt(uid,'📖 Из какого ты отряда? Напиши его название.');return
            self.e.register(uid,p['name'],text);self.ui_clear(uid)
            self.tell_admins(f'📖 Новый гость: {p["name"]}, {text}. ID {uid}. Открой меню мастера → Гости.')
            self.send(uid,'📖 Записал. Теперь дождёмся подтверждения мастера.',BACK);return
        if flow=='action':
            self.e.action_available(uid,p['resource'])
            rid=self.e.request(uid,'action',{'resource':p['resource'],'text':text});self.ui_clear(uid);self.new_request(rid);return
        if flow=='storage':
            rid=self.e.request(uid,'storage',{'direction':p['direction'],'amount':amount()});self.ui_clear(uid);self.new_request(rid);return
        if flow=='spend':
            if step==0:self.ui_set(uid,flow,1,{'amount':amount()});self.ui_prompt(uid,'🍺 На что пойдут монеты?\nНапример: бочонок для гостей или подарок Рою.');return
            rid=self.e.request(uid,'spend',{'amount':p['amount'],'text':text});self.ui_clear(uid);self.new_request(rid);return
        if flow=='trade':
            if step==0:p['give_gold']=amount(True);prompt='🤝 Сколько золота отдаёт второй герой? Если не отдаёт — 0.'
            elif step==1:p['take_gold']=amount(True);prompt='🎒 Какие свои предметы передаёшь?\nНапиши номера из «Мой герой» через запятую. Если нет — дефис: -'
            elif step in (2,3):
                try:ids=[] if text=='-' else [int(x.strip()) for x in text.split(',')]
                except ValueError:raise RuleError('Нужны номера через запятую или один дефис.')
                p['give_items' if step==2 else 'take_items']=ids
                prompt='🎒 Какие предметы передаёт второй герой?\nПопроси его назвать номера из своей карточки. Если нет — дефис: -' if step==2 else '🤝 Коротко опиши договорённость одним сообщением.'
            else:
                rid=self.e.trade(uid,p['other'],p['give_gold'],p['take_gold'],p['give_items'],p['take_items'],text)
                self.ui_clear(uid);self.new_request(rid);return
            self.ui_set(uid,flow,step+1,p);self.ui_prompt(uid,prompt);return
        if flow in ('board','admin_gold','admin_confirm'):
            self.ui_admin_required(uid)
            if flow=='board':
                self.e.db.execute("INSERT OR REPLACE INTO meta VALUES('quest_board',?)",(text,));self.ui_clear(uid);self.send(uid,'📜 Доска обновлена. Игроки увидят текст в меню.',kb([[('🗝 Меню мастера','admin')]]));return
            if flow=='admin_gold':
                if step==0:
                    p['amount']=amount(p['mode']=='set');self.ui_set(uid,flow,1,p);self.ui_prompt(uid,'📒 Какая причина записи? Она останется в журнале.');return
                p['reason']=text
                import secrets
                p['nonce']=secrets.token_hex(4)
                self.ui_set(uid,'admin_confirm',0,p)
                label={'income':'Начислить в доход','expense':'Списать в расход','set':'Установить кошелёк'}[p['mode']]
                self.send(uid,f'📒 ПРОВЕРЬ ЗАПИСЬ\n\nГерой: {self.e.player(p["who"])["name"]}\n{label}: {money(p["amount"])} зм\nПричина: {text}',kb([[('✅ Внести запись',f'confirm:{p["nonce"]}'),('Отменить','cancel')]]));return
            raise RuleError('Подтверди запись кнопкой или отмени ввод.')
        raise RuleError('Неизвестный ввод. Открой /menu.')
