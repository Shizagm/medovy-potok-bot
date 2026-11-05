"""Telegram long-polling transport. Pillow renders portraits; Python 3.11+."""
import json
import logging
import os
from pathlib import Path
import re
import shlex
import signal
import time
import urllib.error
import urllib.request
from datetime import datetime
from engine import Engine, RuleError, ROOMS, TZ

LOG=logging.getLogger('roy')

class TelegramError(Exception): pass

class Telegram:
    def __init__(self, token): self.token=token
    def call(self, method, **data):
        req=urllib.request.Request('https://api.telegram.org/bot'+self.token+'/'+method,
            data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=45) as r: result=json.load(r)
        except urllib.error.HTTPError as exc:
            try: detail=json.loads(exc.read()).get('description','Telegram error')
            except (ValueError,AttributeError): detail='Telegram error'
            raise TelegramError(f'{exc.code}: {detail}') from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise TelegramError('Нет соединения с Telegram') from None
        if not result.get('ok'): raise TelegramError(result.get('description','Telegram error'))
        return result['result']

    def upload_animation(self, path, **data):
        import uuid
        boundary='Roy'+uuid.uuid4().hex
        chunks=[]
        for key,value in data.items():
            chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode())
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="animation"; filename="dice.gif"\r\nContent-Type: image/gif\r\n\r\n').encode())
        chunks.extend([Path(path).read_bytes(),f'\r\n--{boundary}--\r\n'.encode()])
        req=urllib.request.Request('https://api.telegram.org/bot'+self.token+'/sendAnimation',data=b''.join(chunks),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
        try:
            with urllib.request.urlopen(req,timeout=45) as response: result=json.load(response)
        except urllib.error.HTTPError as exc:
            raise TelegramError(f'Ошибка отправки анимации: HTTP {exc.code}') from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise TelegramError('Нет соединения при отправке анимации') from None
        if not result.get('ok'): raise TelegramError(result.get('description','Ошибка анимации'))
        return result['result']

    def upload_photo(self, png, **data):
        import uuid
        boundary='RoyMap'+uuid.uuid4().hex
        chunks=[]
        for key,value in data.items():
            value=json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else str(value)
            chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode())
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="tavern.png"\r\nContent-Type: image/png\r\n\r\n').encode())
        chunks.extend([png,f'\r\n--{boundary}--\r\n'.encode()])
        req=urllib.request.Request('https://api.telegram.org/bot'+self.token+'/sendPhoto',data=b''.join(chunks),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
        try:
            with urllib.request.urlopen(req,timeout=45) as response:result=json.load(response)
        except urllib.error.HTTPError as exc:raise TelegramError(f'Ошибка отправки карты: HTTP {exc.code}') from None
        except (urllib.error.URLError,TimeoutError,OSError):raise TelegramError('Нет соединения при отправке карты') from None
        if not result.get('ok'):raise TelegramError(result.get('description','Ошибка карты'))
        return result['result']

    def download_image(self, file_id):
        from token_rules import MAX_UPLOAD
        from urllib.parse import quote
        info=self.call('getFile',file_id=file_id)
        path=info.get('file_path','')
        if not path or path.startswith('/') or '..' in path.split('/') or not re.fullmatch(r'[A-Za-z0-9_./-]+',path):raise TelegramError('Telegram вернул некорректный путь изображения.')
        if info.get('file_size',0)>MAX_UPLOAD:raise RuleError('Портрет должен быть не больше 5 МБ.')
        try:
            with urllib.request.urlopen('https://api.telegram.org/file/bot'+self.token+'/'+quote(path,safe='/'),timeout=45) as response:
                raw=response.read(MAX_UPLOAD+1)
        except (urllib.error.URLError,TimeoutError,OSError):raise TelegramError('Не удалось скачать портрет из Telegram. Попробуй прислать его снова.') from None
        if len(raw)>MAX_UPLOAD:raise RuleError('Портрет должен быть не больше 5 МБ.')
        return raw

HELP='''Медовый поток · Рой
/profile — профиль, золото, Вдохновение и предметы
/token — портрет для жетона
/enter — войти на карту, если ожидал свободного места
/map — карта и положение
/move L12 — маршрут к клетке; /move rooms W10 — на другой этаж
/poker — выбрать соперника и ставку кнопками
/poker ID СТАВКА — прямой вызов; до двух перебросов, закрытые руки
/pokerview НОМЕР — открыть стол; /pokerroll НОМЕР — бросить пять костей
/roll НОМЕР — назначенный мастером бросок d20
/register Имя | Отряд — заявка на вступление
/ratings — последний опубликованный рейтинг
/act base | описание — основное действие
/act inspiration | описание — дополнительное действие
/rent 1 — койка; /rent 2 — комната; /rent 3 — большая; /rent 0 — съехать
/storage in 100 — положить в сундук; out — забрать
/spend 50 | бочонок для гостей — заявка на расход
/trade ID 100 0 - 12 | пояснение — я даю 100 зм и получаю предмет №12
Порядок trade: ID партнёра, даю золото, получаю золото, мои предметы, его предметы. Несколько номеров — через запятую, отсутствие — дефис.
/request 12 — карточка заявки
/cancel 12 — отмена своей заявки
/history — мои последние операции (без тайных имён)
/id — мой ID и ID текущего чата/темы
Все личные операции — в переписке с ботом. Условия сделки проверяет мастер; соседство автоматически проверяется при включённом режиме карты.'''

ADMIN='''Мастер · команды в личной переписке
/mapadmin — карта, двери, туман, позиции и недельные ходы
/npcs — НПС/монстры и команды их настройки
/playertoken ID — загрузить портрет героя
/players — игроки и ID
/inspect ID — профиль другого героя
/pause ID 1 — приостановить участие и начисления; 0 — возобновить
/notice текст — объявление от Роя группе
/pending — незавершённые заявки
/admit ID — одобрить вступление
/approve НОМЕР — исполнить заявку (после проверки карты)
/reject НОМЕР — отменить заявку
/gold ID delta 200 income | награда — доход и баланс
/gold ID delta -50 expense | расход — расход и баланс
/gold ID set 1000 none | сверка — установить кошелёк; сундук отдельно
Флаги: income / expense / none. set не меняет рейтинг без явного флага.
/rankfix ID 100 -50 | причина — поправить доход/расход месяца без изменения золота
/inspire ID 1 — выдать; 0 — снять
/visit ID — выдать ход за визит (один раз в день)
/check НОМЕР МОДИФИКАТОР СЛОЖНОСТЬ | НАВЫК — мастер бросает d20
/askroll НОМЕР МОДИФИКАТОР СЛОЖНОСТЬ | НАВЫК — назначить игроку кнопку d20
/record НОМЕР КУБИК МОДИФИКАТОР СЛОЖНОСТЬ | НАВЫК — записать бросок за столом
Название навыка после | необязательно. Например: /askroll 2 3 15 | Восприятие. Введи модификатор без штрафа воскрешения.
Покер стартует автоматически после согласия игроков; мастер не нужен.
/pokercancel НОМЕР — отменить партию с возвратом ставок
/item ID | название — добавить предмет
/rob ВОР ЖЕРТВА wallet 30 5 7 2 14 — попытка кражи
После суммы: модификаторы Скрытности, Ловкости рук, Внимательности жертвы и сложность кражи. Вместо Скрытности можно none. Для сундука источник chest; дверь и замок разрешаются отдельно.
/dead ID 1 — перевести в призраки
/hp ID ЧИСЛО — текущее здоровье; 0 переводит в призраки
Возвращение: /resurrect, 1000 зм за выкуп у Шизы. /revive больше не даёт бесплатного возвращения.
/reclaim ID — вернуть золото, хранящееся у Роя
/settle — списать постой до сегодняшнего дня (без повторных списаний)
/publish — опубликовать текущие рейтинги (может раскрыть изменения после краж)
/audit ID — полный журнал мастера
/backup — создать локальную резервную копию
/sync — повторить синхронизацию маркеров Вдохновения
/roygold set 1000 | Причина — игровой кошелёк Роя (delta для пополнения)
/royrob НОМЕР 5 7 2 14 — разрешить попытку обворовать Роя
/shopprice uncommon 400 — цена полки; 0 закрывает полку
/royhistory — журнал игрового кошелька Роя
'''

def keyboard(rows):
    return {'inline_keyboard':[[{'text':label,'callback_data':data} for label,data in row] for row in rows]}

from interface import InterfaceMixin
from feature_interface import FeatureInterfaceMixin
from character_interface import CharacterInterfaceMixin

from map_ui import MapInterfaceMixin

from token_ui import TokenInterfaceMixin

class Bot(TokenInterfaceMixin,MapInterfaceMixin,CharacterInterfaceMixin,FeatureInterfaceMixin,InterfaceMixin):
    def __init__(self, api, engine, admins, group, topic=0):
        self.api,self.e,self.admins,self.group,self.topic=api,engine,set(admins),group,topic
        self.running=True
        self.tag_seen={}
        self.admin_help=ADMIN
        self.interface_schema()

    def send(self, target, text, markup=None, group=False):
        result=None
        chunks=[text[i:i+3500] for i in range(0,len(text),3500)] or ['—']
        for i,chunk in enumerate(chunks):
            args={'chat_id':target,'text':chunk}
            if markup and i==len(chunks)-1: args['reply_markup']=markup
            if group and self.topic: args['message_thread_id']=self.topic
            result=self.api.call('sendMessage',**args)
        return result

    def tell_admins(self, text, markup=None):
        for uid in self.admins:
            # Persist notifications rather than making a state change depend on an admin DM.
            self.e.notify(uid,text)

    def member(self, uid):
        if uid in self.admins: return
        info=self.api.call('getChatMember',chat_id=self.group,user_id=uid)
        if info['status'] not in ('member','administrator','creator','restricted') or (info['status']=='restricted' and not info.get('is_member')):
            raise RuleError('Доступ только участникам закрытой группы таверны.')

    def card(self, rid, viewer=None):
        r=self.e.req(rid); p=r['payload']
        name=lambda uid:self.e.player(uid,False)['name']
        status={'pending':'ожидает решения','done':'исполнена','cancelled':'отменена'}.get(r['status'],r['status'])
        text=f'📨 ЗАПИСЬ №{rid}\n{status.capitalize()} · {name(r["a"])}\n\n'
        if r['kind']=='trade':
            def items(ids):
                return ', '.join(f'№{i} '+self.e.db.execute('SELECT name FROM items WHERE id=?',(i,)).fetchone()[0] for i in ids) or 'нет'
            text+=f'🤝 {name(r["a"])} передаёт: {p["give_gold"]} зм; предметы: {items(p["give_items"])}\n'
            text+=f'{name(r["b"])} даёт: {p["take_gold"]} зм; предметы: {items(p["take_items"])}\n'
            text+=f'Подтверждения: {"да" if r["ca"] else "нет"} / {"да" if r["cb"] else "нет"}\n{p["note"]}'
        elif r['kind']=='action':
            text+=('🖐 Основное действие' if p['resource']=='base' else '✨ Вдохновение Роя')+'\n'+p['text']
        elif r['kind']=='character_update':
            text+='🔒 Изменение закрытой карточки\n'+f"КБ {p['ac']} · Здоровье {p['hp_now']}/{p['hp_max']}\nСкорость {p['speed_ft']} футов · Пассивное Восприятие {p['passive']}\n\nОружие: {p['weapons']}\nБагаж: {p['bag']}"
            if p['hp_now']==0:text+='\n🕯 Одобрение переведёт героя в призраки.'
        elif r['kind']=='roy_theft':text+='🍯 Попытка обворовать Роя\n'+('🖐 Основное действие' if p['resource']=='base' else '✨ Вдохновение Роя')
        elif r['kind']=='rent': text+='Жильё: '+ROOMS[p['tier']][0]
        elif r['kind']=='storage': text+=('Положить в сундук: ' if p['direction']=='in' else 'Забрать из сундука: ')+str(p['amount'])+' зм'
        elif r['kind']=='spend': text+=f"Расход: {p['amount']} зм · {p['text']}"
        buttons=[]
        if r['status']=='pending':
            if r['kind']=='trade': buttons.append([('Подтверждаю',f'confirm:{rid}')])
            buttons.append([('Отменить',f'cancel:{rid}')])
            if viewer in self.admins:
                if r['kind']=='roy_theft':buttons.append([('🎲 Проверки у Роя',f'ui:royresolve:{rid}'),('❌ Отклонить',f'reject:{rid}')])
                else:buttons.append([('✅ Мастер: исполнить',f'approve:{rid}'),('❌ Отклонить',f'reject:{rid}')])
        return text,keyboard(buttons)

    def new_request(self, rid):
        self.refresh_request(rid)

    def refresh_request(self, rid):
        r=self.e.req(rid)
        people=set(x for x in (r['a'],r['b']) if x)|self.admins
        for uid in people:
            text,buttons=self.card(rid,uid)
            self.queue_card(uid,text,buttons,f'request_card:{rid}:{uid}')

    def legacy_profile(self, uid):
        p=self.e.player(uid); held,_=self.e._held(uid)
        escrow=self.e.db.execute("SELECT COALESCE(SUM(stake),0) FROM poker WHERE status IN ('active','showdown') AND (a=? OR b=?)",(uid,uid)).fetchone()[0]
        items=self.e.db.execute('SELECT id,name,source_url FROM items WHERE owner=? ORDER BY id',(uid,)).fetchall()
        return (f'{p["name"]} · {p["party"]}\nID: {uid}\n'
                f'Общий баланс: {p["wallet"]+p["chest"]+p["custody"]+escrow} зм; в банке покера {escrow} зм\n'
                f'Кошелёк: {p["wallet"]} зм (резерв {held})\n'
                f'Сундук: {p["chest"]}/{ROOMS[p["tier"]][2]} зм\nУ Роя: {p["custody"]} зм\n'
                f'Вдохновение Роя: {"есть" if p["inspiration"] else "нет"}\n'
                f'Основное действие: {p["turn"]}; дополнительное за визит использовано: {p["extra_used"]}\n'
                f'Жильё: {ROOMS[p["tier"]][0]}; {ROOMS[p["tier"]][1]} зм/день + питание 1 зм/день\n'
                f'Состояние: {"призрак" if p["dead"] else "жив"}\nПредметы:\n'+
                ('\n'.join(f'№{x["id"]} {x["name"]}'+('\n'+x['source_url'] if x['source_url'] else '') for x in items) or 'нет'))

    def profile(self, uid):
        from character_interface import render_card
        return render_card(self.e.char_snapshot(uid))+'\n\n📒 УЧЁТ ТАВЕРНЫ\n'+self.legacy_profile(uid)

    def check_args(self, tail, count):
        numbers, sep, label = tail.partition('|')
        values = tuple(map(int, numbers.split()))
        if len(values) != count:
            raise RuleError('Проверь количество чисел в команде проверки.')
        label = label.strip() if sep else ''
        if len(label) > 80 or '\n' in label or '\r' in label:
            raise RuleError('Название проверки: одна строка до 80 символов.')
        return values, label

    def check_name(self, rid, label):
        if not label:
            return
        r = self.e.req(rid)
        if r['kind'] != 'action':
            raise RuleError('Проверка назначается заявке действия.')
        r['payload']['check_name'] = label
        self.e.db.execute('UPDATE requests SET payload=? WHERE id=?',
                          (json.dumps(r['payload'], ensure_ascii=False), rid))

    def check_context(self, rid):
        r = self.e.req(rid)
        name = self.e.player(r['a'])['name']
        label = r['payload'].get('check_name', '')
        title = '🎲 ' + ('ПРОВЕРКА: ' + label if label else 'ПРОВЕРКА ДЕЙСТВИЯ')
        return r, title + '\nГерой: ' + name + '\nДействие: ' + r['payload']['text'][:300]

    def roll_result(self, rid, result):
        r, context = self.check_context(rid)
        penalty = result.get('penalty', 0)
        base = result.get('base_modifier', result['modifier'] - penalty)
        modifier_text = (' + ' + str(base)) if base >= 0 else (' − ' + str(abs(base)))
        penalty_text = (' − ' + str(abs(penalty))) if penalty < 0 else (' + ' + str(penalty)) if penalty else ''
        source = 'Бросок за столом · записал мастер.' if result.get('source') == 'table' else 'Бросок d20 в боте.'
        msg = (context + f"\n\nd20: {result['die']}{modifier_text}{penalty_text} = {result['total']}"
               + f"\nСложность: {result['dc']} · " + ('Успех!' if result['success'] else 'Неудача.')
               + (f"\nУчтён штраф после воскрешения: {penalty}." if penalty else '')
               + '\n' + source)
        if result.get('source') == 'table':
            self.e.notify(self.group, msg)
        else:
            self.e.notify(self.group, '@ANIMATION@' + json.dumps({'file': f"d20-{result['die']:02}.gif", 'caption': msg}, ensure_ascii=False))
        self.e.notify(r['a'], msg)

    def queue_card(self, target, text, markup, key):
        self.e.notify(target,'@CARD@'+json.dumps({'text':text,'markup':markup,'key':key},ensure_ascii=False))

    def poker_card(self, gid, viewer=None):
        from games import poker_score
        g=self.e.poker_game(gid)
        name=lambda who:self.e.player(who)['name']
        states={'invited':'вызов','active':'собирают комбинации','showdown':'вскрытие','done':'завершена','cancelled':'отменена'}
        text=f"Покер Роя · стол №{gid} · {states[g['status']]}\n{name(g['a'])} против {name(g['b'])}\nСтавка каждого: {g['stake']} зм · банк {g['stake']*2} зм\n"
        rows=[]
        if g['status']=='invited':
            text+=f"Согласие: {'да' if g['ca'] else 'нет'} / {'да' if g['cb'] else 'нет'}. Деньги спишутся после второго согласия.\n"
            text+='Пять d6, до двух перебросов, закрытые руки. Для начала мастер не нужен.\n24 часа без игрового хода — автоматическое вскрытие текущих рук. Не бросивший проигрывает; если оба не бросили, ставки возвращаются.'
            rows=[[('Принять ставку',f'pokerconfirm:{gid}:{g["version"]}'),('Другая ставка',f'pkoffer:{gid}:{g["version"]}')],
                  [('Отказаться',f'pokercancel:{gid}')]]
        elif g['status']=='active':
            for side in ('a','b'):
                state='готов' if g['ready_'+side] else 'собирает руку' if g['d'+side] else 'ещё не бросил'
                text+=name(g[side])+': '+state+'\n'
            text+='Кости доступны каждому только в личной переписке с Роем.'
            rows=[[('Открыть мою руку',f'pokerview:{gid}')],[('Сдаться',f'pkfoldask:{gid}')]]
        elif g['status']=='showdown':
            text+='Обе комбинации зафиксированы. Менять кости нельзя.\n'
            text+=f"Готовы вскрыть: {'да' if g['show_a'] else 'нет'} / {'да' if g['show_b'] else 'нет'}"
            rows=[[('Вскрываю',f'pokershow:{gid}')]]
        elif g['status']=='done':
            result=json.loads(g['result'])
            if result.get('reveal',True):
                for side,key,label in (('a','da','la'),('b','db','lb')):
                    dice=result.get(key)
                    text+=name(g[side])+': '+(' · '.join(map(str,dice)) if dice else 'нет броска')+' — '+result[label]+'\n'
            text+=('Победитель: '+name(result['winner'])+f". Банк {result['bank']} зм зачислен в кошелёк." if result['winner'] else 'Ничья. Ставки возвращены в кошельки.')
            text+='\n'+result.get('reason','')
        elif g['status']=='cancelled':text+=str(g['result'] or '')
        if viewer is not None:
            side=self.e._poker_side(g,viewer)
            if g['status']=='active':
                text+='\n\nТВОЯ РУКА — видна только тебе\n'
                if g['d'+side]:
                    dice=json.loads(g['d'+side]);combo=poker_score(dice)[1]
                    text+=' · '.join(map(str,dice))+' — '+combo+f"\nПеребросы: {g['r'+side]}/2.\n"
                    if g['ready_'+side]:
                        text+='Комбинация подтверждена. Ждём соперника.';rows=[]
                    else:
                        revision=g['rev_'+side];mask=g['m'+side]
                        rows=[]
                        if g['r'+side]<2:
                            rows.append([(f"{'✓' if mask&(1<<i) else '○'} {i+1}: {v}",f'pokerpick:{gid}:{revision}:{i+1}') for i,v in enumerate(dice)])
                            rows.append([('Перебросить выбранные',f'pokerreroll:{gid}:{revision}')])
                            text+='Отметь кости для переброса. Неотмеченные сохранятся.'
                        rows.append([('Подтвердить комбинацию',f'pokerlock:{gid}:{revision}')])
                        rows.append([('Сдаться',f'pkfoldask:{gid}')])
                else:rows=[[('Бросить пять d6',f'pokerroll:{gid}:{g["rev_"+side]}')],[('Сдаться',f'pkfoldask:{gid}')]]
        return text,keyboard(rows)

    def private_poker(self, gid, uid):
        text,buttons=self.poker_card(gid,uid)
        self.queue_card(uid,text,buttons,f'poker_private:{gid}:{uid}')

    def post_poker(self, gid):
        g=self.e.poker_game(gid);text,buttons=self.poker_card(gid)
        self.queue_card(self.group,text,buttons,f'poker_public:{gid}')
        for who in (g['a'],g['b']):self.private_poker(gid,who)

    def poker_menu(self, uid):
        self.e.require_alive(uid)
        others=self.e.db.execute('SELECT uid,name FROM players WHERE approved=1 AND dead=0 AND paused=0 AND uid!=? ORDER BY name LIMIT 50',(uid,)).fetchall()
        rows=[[(p['name'],f'pkfoe:{p["uid"]}')] for p in others]
        text='Кого вызываешь на покер?\nСтавки списываются из доступного золота: кошелёк, затем сундук. Деньги у Роя и резервы сделок не используются.'
        if not others:text+='\nПока нет других зарегистрированных героев.'
        self.e.notify(uid,'@CARD@'+json.dumps({'text':text,'markup':keyboard(rows)},ensure_ascii=False))

    def execute(self, uid, chat, text, private, thread=0):
        head,_,tail=text.partition(' '); cmd=head.split('@')[0].lower(); tail=tail.strip()
        if cmd=='/id':
            self.send(chat,f'Твой ID: {uid}\nЧат: {chat}\nТема: {thread}'); return
        if cmd in ('/start','/menu'):
            if private:self.ui_home(uid)
            else:self.send(chat,'🍯 Рой ждёт у стойки. Открой личную переписку со мной и отправь /start.')
            return
        if cmd=='/help':
            self.send(chat,HELP,keyboard([[('🍯 Главное меню','ui:home')]]));return
        if chat!=self.group and not private: raise RuleError('Команда доступна в таверне или личной переписке.')
        self.member(uid)
        if cmd in ('/token','/enter','/npc','/npcdel','/npctoken','/npcs','/playertoken'):
            if not private:raise RuleError('Портреты и НПС настраиваются в личной переписке с Роем.')
            self.token_command(uid,cmd,tail);return
        if cmd in ('/map','/move','/mapmode','/mapgrant','/mapplace','/mapdoor','/mapreveal','/mapload','/mapweekly','/mapadmin'):
            if not private:raise RuleError('Открой карту в личной переписке с Роем.')
            self.map_command(uid,cmd,tail);return
        if cmd in ('/ui','/uianswer'):
            if not private:raise RuleError('🍯 Эти кнопки работают в личной переписке с Роем. Открой /start у бота.')
            if cmd=='/uianswer':self.ui_answer(uid,tail)
            else:
                words=tail.split();action=words[0] if words else 'home'
                # Reuse existing permission checks for all native game/business routes.
                if action in ('poker','ratings','history'):
                    self.execute(uid,chat,'/'+action,True);return
                if action=='request':
                    self.execute(uid,chat,'/request '+words[1],True);return
                self.ui_dispatch(uid,tail)
            return
        if cmd=='/ratings':
            row=self.e.db.execute("SELECT value FROM meta WHERE key='public_ranks'").fetchone()
            self.send(chat,row[0] if row else '🏆 КНИГА ДОСТИЖЕНИЙ\n\nПервую запись сделаем после публикации мастером.',keyboard([[('🍯 К стойке Роя','ui:home')]]) if private else None); return
        if cmd in ('/character','/resurrect','/dossiers'):
            if not private:raise RuleError('Открой личную переписку с Роем.')
            if cmd=='/character':self.ui_hero(uid)
            else:self.character_ui(uid,'resmenu' if cmd=='/resurrect' else 'dossiers')
            return
        if cmd=='/roll':
            rid=int(tail); result=self.e.player_roll(rid,uid); self.roll_result(rid,result); return
        if cmd=='/poker':
            if not tail:self.poker_menu(uid)
            else:
                other,stake=map(int,shlex.split(tail));self.post_poker(self.e.poker_invite(uid,other,stake))
            return
        if cmd=='/pkfoe':
            other=int(tail);self.e.player(uid);opponent=self.e.player(other)
            rows=[[(str(n)+' зм',f'pkbetto:{other}:{n}') for n in (10,50,100)],[(str(n)+' зм',f'pkbetto:{other}:{n}') for n in (250,500,1000)]]
            self.send(uid,'Ставка против '+opponent['name']+f'. Другая сумма: /poker {other} 200',keyboard(rows));return
        if cmd=='/pkbetto':
            other,stake=map(int,tail.split());self.post_poker(self.e.poker_invite(uid,other,stake));return
        if cmd in ('/pokerview','/pokerconfirm','/pokerroll','/pokercancel','/pokerpick','/pokerreroll','/pokerlock','/pokershow','/pokerfold','/pokerbet','/pkoffer','/pknew','/pkfoldask','/pokerstart'):
            values=tail.split();gid=int(values[0]);g=self.e.poker_game(gid)
            if cmd=='/pokerstart':raise RuleError('Мастер больше не открывает стол: игра стартует после принятия ставки соперником.')
            if cmd=='/pokerview':
                if uid in (g['a'],g['b']):self.private_poker(gid,uid)
                else:
                    text,buttons=self.poker_card(gid);self.send(chat,text,buttons,group=chat==self.group)
                return
            if cmd=='/pokercancel':
                self.e.poker_cancel(gid,uid,uid in self.admins);self.post_poker(gid);return
            self.e._poker_side(g,uid)
            if cmd=='/pokerconfirm':self.e.poker_confirm(gid,uid,int(values[1]) if len(values)>1 else g['version'])
            elif cmd=='/pkoffer':
                version=int(values[1])
                if g['status']!='invited' or version!=g['version']:raise RuleError('Предложение уже изменилось.')
                self.send(uid,'Предложи ставку. Для своей суммы: /pokerbet '+str(gid)+' СУММА',keyboard([[(str(n)+' зм',f'pknew:{gid}:{version}:{n}') for n in (10,50,100)],[(str(n)+' зм',f'pknew:{gid}:{version}:{n}') for n in (250,500,1000)]]));return
            elif cmd in ('/pokerbet','/pknew'):
                version=int(values[1]) if cmd=='/pknew' else g['version']
                stake=int(values[2]) if cmd=='/pknew' else int(values[1])
                self.e.poker_offer(gid,uid,stake,version)
            elif cmd=='/pokerroll':self.e.poker_roll(gid,uid,int(values[1]) if len(values)>1 else None)
            elif cmd=='/pokerpick':
                self.e.poker_pick(gid,uid,int(values[2]),int(values[1]));self.private_poker(gid,uid);return
            elif cmd=='/pokerreroll':self.e.poker_reroll(gid,uid,int(values[1]))
            elif cmd=='/pokerlock':self.e.poker_lock(gid,uid,int(values[1]))
            elif cmd=='/pokershow':self.e.poker_show(gid,uid)
            elif cmd=='/pkfoldask':
                if g['status'] not in ('active','showdown'):raise RuleError('Партия уже закрыта.')
                self.send(uid,f'Сдаться за столом №{gid}? Ты потеряешь ставку {g["stake"]} зм; весь банк получит соперник.',keyboard([[('Да, сдаюсь',f'pokerfold:{gid}')]]));return
            elif cmd=='/pokerfold':self.e.poker_fold(gid,uid)
            self.post_poker(gid);return
        if not private: raise RuleError('Эту команду отправь боту лично: балансы и заявки приватны.')
        if cmd=='/admin':
            if uid not in self.admins: raise RuleError('Только мастер.')
            if tail=='commands':self.send(uid,ADMIN)
            else:self.ui_admin(uid)
            return
        if cmd=='/register':
            name,party=self.parts(tail,2)
            self.e.register(uid,name,party); self.tell_admins(f'Заявка на вступление: {name}, {party}, ID {uid}. /admit {uid}')
            self.send(uid,'Заявка отправлена Рою. Дождись одобрения мастера.'); return
        if cmd in ('/profile','/history'):
            self.e.player(uid)
            if cmd=='/profile':self.ui_hero(uid)
            else:
                lines=[f'{r["day"]} {r["delta"]:+} зм · '+('Кража / попытка: детали у мастера' if r['kind'] in ('theft','theft_attempt','robbed','roy_attempt') else r['reason']) for r in self.e.ledger_for(uid)]
                self.send(uid,'📒 КНИГА РАСЧЁТОВ\n\n'+('\n'.join(lines) or 'Пока нет операций.'),keyboard([[('🪙 Кошелёк','ui:wallet'),('🍯 Меню','ui:home')]]))
            return
        if cmd=='/archive':
            if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',tail): raise RuleError('Месяц в формате 2026-11.')
            result=self.e.rankings(tail)
            lines=[f'Архив {tail}']
            for label in ('Заработок месяца','Гуляка таверны'):
                lines.append(label)
                lines.extend(f'{i}. {name}: {amount} зм' for i,(name,amount) in enumerate(result[label],1))
            self.send(uid,'\n'.join(lines)); return
        if cmd=='/request':
            rid=int(tail); r=self.e.req(rid)
            if uid not in self.admins and uid not in (r['a'],r['b']): raise RuleError('Чужая заявка.')
            self.send(uid,*self.card(rid,uid)); return
        if cmd=='/cancel':
            rid=int(tail);self.e.cancel(rid,uid,uid in self.admins);self.refresh_request(rid);self.send(uid,'📒 Запись отменена.');return
        if cmd=='/confirm':
            rid=int(tail); r=self.e.confirm(rid,uid)
            self.refresh_request(rid)
            if r['ca'] and r['cb']: self.tell_admins(f'Оба согласны на сделку №{rid}. /request {rid}')
            return
        if cmd=='/act':
            resource,desc=self.parts(tail,2)
            if resource not in ('base','inspiration'): raise RuleError('Ресурс: base или inspiration.')
            self.new_request(self.e.request(uid,'action',dict(resource=resource,text=desc))); return
        if cmd=='/rent':
            tier=int(tail)
            if tier not in ROOMS: raise RuleError('Номер жилья: 0–3.')
            self.new_request(self.e.request(uid,'rent',dict(tier=tier))); return
        if cmd=='/storage':
            direction,amount=shlex.split(tail)
            if direction not in ('in','out') or int(amount)<=0: raise RuleError('Формат: /storage in 100 или out 100.')
            self.new_request(self.e.request(uid,'storage',dict(direction=direction,amount=int(amount)))); return
        if cmd=='/spend':
            amount,desc=self.parts(tail,2)
            if int(amount)<=0: raise RuleError('Нужна положительная сумма.')
            self.new_request(self.e.request(uid,'spend',dict(amount=int(amount),text=desc))); return
        if cmd=='/trade':
            terms,note=self.parts(tail,2)
            other,give,take,gi,ti=shlex.split(terms)
            ids=lambda s:[] if s=='-' else [int(x) for x in s.split(',')]
            self.new_request(self.e.trade(uid,int(other),int(give),int(take),ids(gi),ids(ti),note)); return
        if uid not in self.admins: raise RuleError('Неизвестная команда или доступ только мастеру. /help')
        args=shlex.split(tail)
        if cmd=='/inspect': self.send(uid,self.profile(int(tail))); return
        if cmd=='/players':
            rows=self.e.db.execute('SELECT uid,name,party,approved FROM players ORDER BY uid').fetchall()
            self.send(uid,'\n'.join(f'{r["uid"]}: {r["name"]} · {r["party"]} · одобрен={r["approved"]}' for r in rows) or 'Пока пусто.'); return
        if cmd=='/pending':
            rows=self.e.db.execute("SELECT id,kind,a FROM requests WHERE status='pending' ORDER BY id LIMIT 50").fetchall()
            self.send(uid,'\n'.join(f'№{r["id"]} {r["kind"]} ID {r["a"]}: /request {r["id"]}' for r in rows) or 'Заявок нет.'); return
        if cmd=='/admit': self.e.approve(int(tail))
        elif cmd=='/pause': self.e.pause(*map(int,args))
        elif cmd=='/notice':
            if not tail: raise RuleError('Добавь текст объявления.')
            self.e.notify(self.group,tail)
        elif cmd=='/reject':
            self.e.cancel(int(tail),uid,True);self.refresh_request(int(tail))
        elif cmd=='/approve':
            r=self.e.approve_request(int(tail));self.refresh_request(int(tail))
            if r['kind']=='action' and r['payload']['resource']=='inspiration':
                name=self.e.player(r['a'])['name']
                self.e.notify(self.group,f'✨ {name} использовал Вдохновение Роя и получает дополнительное действие.')
        elif cmd=='/gold':
            fields,reason=self.parts(tail,2); who,mode,amount,flag=shlex.split(fields)
            if flag not in ('income','expense','none'): raise RuleError('Флаг: income/expense/none.')
            self.e.adjust(int(who),int(amount),reason,mode,flag=='income',flag=='expense')
        elif cmd=='/rankfix':
            fields,reason=self.parts(tail,2); who,earned,spent=map(int,shlex.split(fields))
            self.e.rank_adjust(who,earned,spent,reason)
        elif cmd=='/inspire': self.e.inspiration(int(args[0]),int(args[1]))
        elif cmd=='/visit': self.e.visit(int(tail))
        elif cmd=='/check':
            (rid,mod,dc),label=self.check_args(tail,3)
            result=self.e.check(rid,mod,dc)
            self.check_name(rid,label)
            self.roll_result(rid,result)
        elif cmd=='/record':
            (rid,die,mod,dc),label=self.check_args(tail,4)
            result=self.e.check(rid,mod,dc,die=die)
            self.check_name(rid,label)
            self.roll_result(rid,result)
        elif cmd=='/askroll':
            (rid,mod,dc),label=self.check_args(tail,3)
            self.e.assign_check(rid,mod,dc)
            self.check_name(rid,label)
            r,context=self.check_context(rid)
            penalty=self.e.weakness(r['a'])
            msg=(context+f'\n\nМодификатор навыка: {mod:+}'
                 +(f'\nШтраф после воскрешения: {penalty}' if penalty else '')
                 +f'\nСложность: {dc}\n\nГерой, указанный выше, может нажать кнопку один раз.')
            buttons=keyboard([[('🎲 Бросить d20',f'roll:{rid}')]])
            self.send(self.group,msg,buttons,group=True)
            self.send(r['a'],msg,buttons)
        elif cmd=='/item':
            who,name=self.parts(tail,2); iid=self.e.add_item(int(who),name); self.send(uid,f'Предмет №{iid}')
        elif cmd=='/rob':
            if len(args)!=8: raise RuleError('Формат /rob: см. /admin')
            thief,victim=int(args[0]),int(args[1]); source=args[2]; amount=int(args[3])
            stealth=None if args[4]=='none' else int(args[4])
            result=self.e.rob(thief,victim,amount,source,stealth,*map(int,args[5:]))
            self.e.notify(thief,'Попытка кражи: '+json.dumps({k:result[k] for k in ('stealth','hands','success','detected','thief_penalty')},ensure_ascii=False))
            self.send(uid,'Закрытый результат: '+json.dumps(result,ensure_ascii=False))
        elif cmd=='/dead':
            if args[1] not in ('0','1'): raise RuleError('Состояние: 0/1.')
            self.e.life(int(args[0]),args[1]=='1')
        elif cmd=='/revive':raise RuleError('Возвращение теперь стоит 1000 зм. Плательщик открывает /resurrect и подтверждает выкуп.')
        elif cmd=='/hp':self.e.set_hp(*map(int,args))
        elif cmd=='/reclaim': self.e.reclaim(int(tail))
        elif cmd=='/settle': self.e.settle()
        elif cmd=='/publish': self.publish()
        elif cmd=='/audit':
            self.e.player(int(tail)); self.send(uid,'\n'.join(f'#{r["id"]} {r["day"]} {r["kind"]} {r["delta"]:+} доход {r["earned"]} расход {r["spent"]} · {r["reason"]}' for r in self.e.ledger_for(int(tail),25)) or 'Пусто.')
        elif cmd=='/backup':
            # SQLite backup cannot run while the update transaction is open.
            self.e.db.execute("INSERT OR REPLACE INTO meta VALUES('backup_requested','1')")
        elif cmd=='/roygold':
            fields,reason=self.parts(tail,2);mode,amount=fields.split()
            self.e.roy_adjust(uid,int(amount),reason,mode)
        elif cmd=='/royrob':
            rid=int(args[0]);stealth=None if args[1]=='none' else int(args[1])
            result=self.e.roy_resolve(rid,stealth,*map(int,args[2:]))
            self.refresh_request(rid);self.feature_roy_result(rid,result)
        elif cmd=='/shopprice':self.e.shop_set_price(args[0],int(args[1]))
        elif cmd=='/royhistory':
            rows=self.e.db.execute('SELECT * FROM roy_ledger ORDER BY id DESC LIMIT 25').fetchall()
            self.send(uid,'🍯 ИГРОВОЕ ЗОЛОТО РОЯ\n\n'+('\n'.join(f"{r['day']} {r['delta']:+} зм · {r['reason']}" for r in rows) or 'Записей пока нет.'))
        elif cmd=='/sync': self.tag_seen.clear()
        else: raise RuleError('Неизвестная команда. /admin')
        self.send(uid,'Готово. Рой внёс запись.')

    @staticmethod
    def parts(text,n):
        parts=[x.strip() for x in text.split('|',n-1)]
        if len(parts)!=n or any(not x for x in parts): raise RuleError('Разделяй поля символом |. Форматы: /help или /admin.')
        return parts

    def publish(self):
        now=str(self.e.clock()); lines=[f'🏆 КНИГА ДОСТИЖЕНИЙ\nМедовый поток · {now}\nМесяц: {now[:7]}']
        for label,rows in self.e.rankings().items():
            icon={'Самые богатые':'🪙','Заработок месяца':'💰','Гуляка таверны':'🍺'}[label]
            lines.append('\n'+icon+' '+label)
            lines.extend(f"{('🥇','🥈','🥉')[i-1] if i<=3 else str(i)+'.'} {name} — {amount:,} зм".replace(',',' ') for i,(name,amount) in enumerate(rows,1))
        text='\n'.join(lines)
        self.e.db.execute("INSERT OR REPLACE INTO meta VALUES('public_ranks',?)",(text,))
        self.e.notify(self.group,text)

    def handle(self, update):
        previous=self.e.db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
        if previous and update['update_id']<int(previous[0]): return
        cb=update.get('callback_query'); msg=update.get('message')
        if cb:
            msg=cb.get('message',{}); uid=cb['from']['id']; data=cb.get('data','')
            if data.startswith('ui:'):text='/ui '+data[3:].replace(':',' ')
            elif data in ('profile','ratings','poker'): text='/'+data
            elif re.fullmatch(r'(confirm|cancel|approve|reject|roll|pokerview|pokerconfirm|pokerroll|pokerstart|pokercancel|pokerpick|pokerreroll|pokerlock|pokershow|pokerfold|pkfoe|pkbetto|pkoffer|pknew|pkfoldask):[0-9]+(?::[0-9]+){0,2}',data): text='/'+data.replace(':',' ')
            else: return
            try: self.api.call('answerCallbackQuery',callback_query_id=cb['id'])
            except TelegramError: pass
        elif msg and (msg.get('photo') or msg.get('document')) and msg.get('chat',{}).get('type')=='private':
            uid=msg.get('from',{}).get('id')
            if not uid or msg.get('sender_chat'):return
            try:
                with self.e.tx():
                    self.token_receive(uid,msg)
                    self.e.db.execute("INSERT OR REPLACE INTO meta VALUES('offset',?)",(str(update['update_id']+1),))
            except RuleError as exc:self.send(uid,str(exc))
            return
        elif msg and msg.get('text','').startswith('/'):
            uid=msg.get('from',{}).get('id'); text=msg['text']
        elif msg and msg.get('text') and msg.get('chat',{}).get('type')=='private' and self.ui_state(msg.get('from',{}).get('id')):
            uid=msg['from']['id'];text='/uianswer '+msg['text']
        else: return
        if not uid or msg.get('sender_chat'): return
        chat=msg['chat']['id']; private=msg['chat']['type']=='private'
        try:
            with self.e.tx():
                self.execute(uid,chat,text,private,msg.get('message_thread_id',0))
                self.e.db.execute("INSERT OR REPLACE INTO meta VALUES('offset',?)",(str(update['update_id']+1),))
        except (RuleError,ValueError,IndexError,TypeError) as exc:
            detail=str(exc) if isinstance(exc,RuleError) else 'Проверь формат команды: /help или /admin.'
            self.send(chat,detail)

    def housekeeping(self):
        self.e.map_tick()
        for gid in self.e.expire_poker():self.post_poker(gid)
        today=self.e.clock(); monday=today.fromordinal(today.toordinal()-today.weekday())
        row=self.e.db.execute("SELECT value FROM meta WHERE key='week'").fetchone()
        if not row or row[0]!=str(monday):
            with self.e.tx():
                self.e.weekly(); self.publish()
                self.e.db.execute("INSERT OR REPLACE INTO meta VALUES('week',?)",(str(monday),))
        if self.e.db.execute("SELECT 1 FROM meta WHERE key='backup_requested'").fetchone():
            target=Path(os.environ.get('BACKUP_DIR','data/backups')); target.mkdir(parents=True,exist_ok=True)
            path=target/(datetime.now(TZ).strftime('%Y%m%d-%H%M%S')+'.sqlite3')
            self.e.backup(str(path))
            self.e.db.execute("DELETE FROM meta WHERE key='backup_requested'")
            self.tell_admins(f'Резервная копия создана: {path.name}')
        for p in self.e.db.execute('SELECT uid,inspiration FROM players WHERE approved=1'):
            if self.tag_seen.get(p['uid'])==p['inspiration']: continue
            try:
                self.api.call('setChatMemberTag',chat_id=self.group,user_id=p['uid'],tag='Вдохновение' if p['inspiration'] else '')
                self.tag_seen[p['uid']]=p['inspiration']
            except TelegramError:
                # Retry once per minute, not on every update. Resource remains in DB.
                if not hasattr(self,'tag_error_at') or time.time()-self.tag_error_at>3600:
                    self.tell_admins('Не удалось обновить маркер Вдохновения. Проверь право бота управлять тегами и что игрок — обычный участник, не администратор. Баланс Вдохновения сохранён.')
                    self.tag_error_at=time.time()
        for row in self.e.db.execute('SELECT * FROM outbox WHERE sent=0 ORDER BY id LIMIT 40').fetchall():
            try:
                if row['text'].startswith('@MAP@'):
                    request=json.loads(row['text'][len('@MAP@'):])
                    png,caption,markup=self.map_photo(request['uid'],request['area'])
                    self.api.upload_photo(png,chat_id=row['target'],caption=caption,reply_markup=markup)
                elif row['text'].startswith('@CARD@'):
                    card=json.loads(row['text'][len('@CARD@'):])
                    key=card.get('key')
                    previous=self.e.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone() if key else None
                    if previous and len(card['text'])<=3500:
                        try:
                            self.api.call('editMessageText',chat_id=row['target'],message_id=int(previous[0]),text=card['text'][:4000],reply_markup=card['markup'])
                        except TelegramError as exc:
                            if 'message is not modified' not in str(exc):
                                if 'message to edit not found' in str(exc) or "message can't be edited" in str(exc):
                                    result=self.send(row['target'],card['text'],card['markup'],group=row['target']==self.group)
                                    self.e.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,str(result['message_id'])))
                                else:raise
                    else:
                        result=self.send(row['target'],card['text'],card['markup'],group=row['target']==self.group)
                        if key:self.e.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,str(result['message_id'])))
                elif row['text'].startswith('@ANIMATION@'):
                    media=json.loads(row['text'][len('@ANIMATION@'):])
                    if not re.fullmatch(r'd20-(0[1-9]|1[0-9]|20)\.gif',media['file']): raise TelegramError('Некорректное имя анимации')
                    kw={'chat_id':row['target'],'caption':media['caption'][:1024]}
                    if self.topic and row['target']==self.group: kw['message_thread_id']=self.topic
                    self.api.upload_animation(Path(__file__).resolve().parent/'assets'/media['file'],**kw)
                else:
                    self.send(row['target'],row['text'],group=row['target']==self.group)
                self.e.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['id'],))
            except TelegramError:
                # Other recipients still receive their messages; pending DMs retry later.
                continue

    def run(self):
        next_house=0
        while self.running:
            try:
                if time.time()>=next_house:
                    self.housekeeping(); next_house=time.time()+60
                row=self.e.db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
                offset=int(row[0]) if row else 0
                updates=self.api.call('getUpdates',offset=offset,timeout=25,allowed_updates=['message','callback_query'])
                for update in updates:
                    try: self.handle(update)
                    except Exception as exc:
                        # Never log Telegram request URLs (they contain the token).
                        LOG.error('Update failed: %s',type(exc).__name__)
                        self.tell_admins('Не удалось обработать команду. Изменения откатились; проверь /audit и повтори её.')
                    self.e.db.execute("INSERT OR REPLACE INTO meta VALUES('offset',?)",(str(update['update_id']+1),))
                # Deliver committed notifications promptly.
                for p in self.e.db.execute('SELECT uid,inspiration FROM players WHERE approved=1'):
                    if self.tag_seen.get(p['uid'])!=p['inspiration']: next_house=0
                if updates: next_house=0
            except TelegramError as exc:
                LOG.warning('%s',exc); time.sleep(5)
            except Exception as exc:
                LOG.error('Background failed: %s',type(exc).__name__); time.sleep(5)


def load_env(path='.env'):
    if Path(path).exists():
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('\"').strip("'"))

def main():
    os.chdir(Path(__file__).resolve().parent)
    load_env(); logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    token=os.environ.get('BOT_TOKEN','')
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+',token): raise SystemExit('Укажи BOT_TOKEN в .env')
    try:
        admins={int(x.strip()) for x in os.environ['ADMIN_IDS'].split(',') if x.strip()}
        group=int(os.environ['TAVERN_CHAT_ID'])
        if not admins or group>=0: raise ValueError()
    except (ValueError,KeyError): raise SystemExit('Укажи ADMIN_IDS и отрицательный TAVERN_CHAT_ID в .env')
    db = os.environ.get('DB_PATH', 'data/tavern.sqlite3')
    # Keep the lock: never permit concurrent writers to the same database.
    from instance_lock import InstanceLock
    try:
        Path(db).parent.mkdir(parents=True, exist_ok=True)
        lock = InstanceLock(db + '.lock')
    except BlockingIOError as exc:
        raise SystemExit(f'База занята другим процессом: {db}. Подробности: {exc}') from None
    except OSError as exc:
        raise SystemExit(f'Ошибка доступа к базе или блокировке {db}: {exc}') from None
    bot=Bot(Telegram(token),Engine(db),admins,group,int(os.environ.get('PUBLIC_TOPIC_ID','0')))
    for sig in (signal.SIGTERM,signal.SIGINT): signal.signal(sig,lambda *_:setattr(bot,'running',False))
    try:
        webhook=bot.api.call('getWebhookInfo')
        if webhook.get('url'): raise SystemExit('У этого бота уже настроен webhook. Используй отдельного нового бота или отключи webhook осознанно.')
        bot.api.call('getMe')
    except TelegramError as exc:
        raise SystemExit(str(exc)) from None
    LOG.info('Рой готов. Остановка: Ctrl+C.')
    try:
        bot.run()
    finally:
        bot.e.db.close()
        lock.close()

if __name__=='__main__': main()
