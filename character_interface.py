"""Private stats UI; snapshots and resurrection are owner-confirmed purchases."""
import secrets
from engine import RuleError
from interface import kb,BACK,money


def render_card(c, title='👤 КАРТОЧКА ПЕРСОНАЖА'):
    value=lambda k:'не указано' if c[k] is None else str(c[k])
    text=f'{title}\n{c["name"]}\n\nСостояние: '+('🕯 призрак' if c['dead'] else '🟢 жив')
    text+=f'\nКласс брони: {value("ac")}\nЗдоровье: {value("hp_now")}/{value("hp_max")}\nСкорость: {value("speed_ft")} футов\nПассивное Восприятие: {value("passive")}\n'
    if c['speed_ft'] is not None:text+=f'Клеток по 5 футов: {c["speed_ft"]//5}\n'
    text+='\nОружие\n'+(c['weapons'] or 'не указано')+'\n\nБагаж\n'+(c['bag'] or 'не указано')
    if c['items']:text+='\n\nУчтённые предметы\n'+'\n'.join('• '+item['name'] for item in c['items'])
    text+='\n\nШтраф к проверкам: '+(str(c['penalty']) if c['penalty'] else 'нет')
    if c['next_recovery']:text+='\nСледующее ослабление: '+c['next_recovery']
    text+='\nКарточка подтверждена: '+(c['updated'] or 'ожидает заполнения')
    return text

class CharacterInterfaceMixin:
    def ui_hero(self,uid):
        p=self.e.player(uid);snap=self.e.char_snapshot(uid)
        text=render_card(snap)+'\n\n✨ Вдохновение Роя: '+('есть' if p['inspiration'] else 'нет')
        text+='\n🖐 Основное действие: '+('запрещено призраку' if p['dead'] else 'доступно' if p['turn'] else 'сейчас нет')
        text+='\n🎯 Дополнительное за визит: '+('уже использовано' if p['extra_used'] else 'ещё не использовано')
        text+='\n\n🔒 Полную карточку видят ты, мастер и купивший её снимок герой.'
        if p['dead']:rows=[[('🕯 Выкупить себя · 1000 зм','resoffer:'+str(uid))],[('🍯 Меню','home')]]
        else:rows=[[('📝 Заполнить / обновить карточку','charedit')],[('🖐 Сделать ход','actions'),('🪙 Кошелёк','wallet')],[('📚 Купленные сведения','dossiers'),('🍯 Меню','home')]]
        rows.insert(0,[('🟣 Портрет жетона','token')])
        self.send(uid,text,kb(rows))

    def ui_wallet(self,uid):
        p=self.e.player(uid)
        if not p['dead']:return super().ui_wallet(uid)
        total=p['wallet']+p['chest']+p['custody']+self.ui_escrow(uid)
        text=f'🪙 ЗОЛОТО ПРИЗРАКА\n{p["name"]}\n\nВсего: {money(total)} зм\nКошелёк: {money(p["wallet"])} зм\nСундук: {money(p["chest"])} зм\nУ Роя: {money(p["custody"])} зм\n\nТорговля и покупки закрыты. Для выкупа себя у Шизы можно потратить 1000 зм из кошелька и сундука.'
        self.send(uid,text,kb([[('🕯 Выкупить себя',f'resoffer:{uid}')],[('🍯 Меню','home')]]))

    def character_ui(self,uid,tail):
        args=tail.split();action=args[0] if args else ''
        known={'charedit','charadmin','charlist','infooffer','infobuy','infosaved','dossiers','resmenu','resoffer','respay','hpedit','hpconfirm'}
        if action not in known:return False
        if action in ('charadmin','hpedit','hpconfirm'):self.ui_admin_required(uid)
        if action in ('charedit','charadmin'):
            target=int(args[1]) if action=='charadmin' else uid
            if action=='charedit':self.e.require_alive(uid)
            self.e.player(target)
            self.ui_set(uid,'char_edit',payload={'target':target,'editor':uid if action=='charadmin' else None})
            old=self.e.char_data(target)
            self.ui_prompt(uid,'📝 КАРТОЧКА ГЕРОЯ\n\nКласс брони? Напиши число.\nСейчас: '+str(old['ac'] if old['ac'] is not None else 'не указан'));return True
        if action=='charlist':
            rows=self.e.db.execute('SELECT uid,name FROM players WHERE approved=1 AND uid!=? ORDER BY name LIMIT 50',(uid,)).fetchall()
            buttons=[[(r['name'],f'infooffer:{r["uid"]}')] for r in rows]
            buttons.append([('📚 Мои справки','dossiers'),('🍯 Меню','home')])
            self.send(uid,'🔎 СВЕДЕНИЯ РОЯ\n\nПублично известно только имя героя. За 500 зм Рой даст текущий снимок его карточки: защиту, здоровье, скорость, оружие, багаж и пассивное Восприятие.',kb(buttons));return True
        if action=='infooffer':
            target=int(args[1]);oid=self.e.info_prepare(uid,target)
            self.send(uid,f'🔎 Сведения о {self.e.player(target)["name"]}\n\nЦена: 500 игровых зм. Справка останется у тебя, но не будет обновляться после изменений героя.\n\nДеньги списываются из кошелька, затем сундука.',kb([[('🪙 Купить сведения · 500 зм',f'infobuy:{oid}')],[('← К именам','charlist'),('🍯 Меню','home')]]));return True
        if action=='infobuy':
            snap,already=self.e.info_pay(int(args[1]),uid)
            self.queue_card(uid,render_card(snap,'🔎 СВЕДЕНИЯ РОЯ')+'\n\nСнимок на '+snap['snapshot_day']+(' · ранее оплачено.' if already else ' · оплачено 500 зм.'),kb([[('📚 Мои справки','dossiers'),('🍯 Меню','home')]]),f'info_snapshot:{args[1]}');return True
        if action=='dossiers':
            rows=self.e.db.execute("SELECT id,snapshot FROM info_orders WHERE buyer=? AND status='done' ORDER BY id DESC LIMIT 30",(uid,)).fetchall()
            import json
            buttons=[]
            for row in rows:
                snap=json.loads(row['snapshot']);buttons.append([(snap['name']+' · '+snap['snapshot_day'],f'infosaved:{row["id"]}')])
            buttons.append([('🔎 Узнать о герое','charlist'),('🍯 Меню','home')])
            self.send(uid,'📚 МОИ СВЕДЕНИЯ\n\n'+('Сохранённые снимки карточек.' if rows else 'Пока нет оплаченных справок.'),kb(buttons));return True
        if action=='infosaved':
            snap=self.e.info_saved(int(args[1]),uid)
            self.send(uid,render_card(snap,'📚 СОХРАНЁННЫЕ СВЕДЕНИЯ')+'\n\nСнимок на '+snap['snapshot_day'],kb([[('📚 Назад','dossiers'),('🍯 Меню','home')]]));return True
        if action=='resmenu':
            p=self.e.player(uid)
            if p['dead']:targets=[p]
            else:targets=[dict(r) for r in self.e.db.execute('SELECT uid,name FROM players WHERE approved=1 AND dead=1 AND paused=0 ORDER BY name LIMIT 50')]
            buttons=[[(r['name']+' · 1000 зм',f'resoffer:{r["uid"]}')] for r in targets]+[[('🍯 Меню','home')]]
            self.send(uid,'🕯 ВЫКУП У ШИЗЫ\n\n'+('Кого возвращаем к жизни?' if targets else 'Сейчас нет героев, которым нужен выкуп.'),kb(buttons));return True
        if action=='resoffer':
            target=int(args[1]);oid=self.e.res_prepare(uid,target)
            self.send(uid,f'🕯 ВЫКУП У ШИЗЫ\n{self.e.player(target)["name"]}\n\nЦена: 1000 зм из твоего золота.\nПосле возвращения: полное здоровье, штраф −4 ко всем активным проверкам. Он ослабевает на 1 каждые 7 дней.\n\nВыкуп не тратит действие. Списания не будет, если герой уже жив.',kb([[('🕯 Оплатить выкуп · 1000 зм',f'respay:{oid}')],[('🍯 Меню','home')]]));return True
        if action=='respay':
            target,already=self.e.res_pay(int(args[1]),uid)
            self.queue_card(uid,('Этот выкуп уже исполнен.' if already else '🕯 Шиза принял выкуп. Герой снова жив.')+'\n'+self.e.player(target)['name'],BACK,f'resurrection_receipt:{args[1]}')
            if not already:self.e.notify(self.group,'🕯 Шиза вернул к жизни '+self.e.player(target)['name']+'. Жетон можно перевернуть лицевой стороной.')
            return True
        if action=='hpedit':
            target=int(args[1]);self.e.player(target)
            self.ui_set(uid,'hp_edit',payload={'target':target})
            c=self.e.char_data(target)
            self.ui_prompt(uid,f'❤️ {self.e.player(target)["name"]}\nЗдоровье: {c["hp_now"]}/{c["hp_max"]}\n\nКакое текущее здоровье установить? 0 переведёт героя в призраки.');return True
        if action=='hpconfirm':
            st=self.ui_state(uid)
            if not st or st['flow']!='hp_confirm' or len(args)<2 or args[1]!=st['payload']['nonce']:raise RuleError('Это подтверждение уже неактуально.')
            p=st['payload'];self.e.set_hp(p['target'],p['hp']);self.ui_clear(uid)
            self.send(uid,'❤️ Здоровье обновлено.',kb([[('🗝 Меню мастера','admin')]]));return True
        return False

    def character_answer(self,uid,text,st):
        flow,step,p=st['flow'],st['step'],st['payload']
        if flow not in ('char_edit','hp_edit','hp_confirm'):return False
        if flow in ('hp_edit','hp_confirm'):self.ui_admin_required(uid)
        if flow=='hp_confirm':raise RuleError('Используй кнопку подтверждения.')
        if flow=='hp_edit':
            try:hp=int(text)
            except ValueError:raise RuleError('Нужно целое число здоровья.')
            c=self.e.char_data(p['target'])
            if c['hp_max'] is None or not 0<=hp<=c['hp_max']:raise RuleError('Проверь максимум здоровья в карточке.')
            p.update(hp=hp,nonce=secrets.token_hex(4));self.ui_set(uid,'hp_confirm',payload=p)
            self.send(uid,f'❤️ Установить здоровье {hp}/{c["hp_max"]}?'+('\nГерой станет призраком, активные сделки и покер остановятся.' if hp==0 else ''),kb([[('✅ Подтвердить',f'hpconfirm:{p["nonce"]}'),('Отменить','cancel')]]));return True
        if p.get('editor') is not None:self.ui_admin_required(uid)
        else:self.e.require_alive(uid)
        try:
            if step==0:
                p['ac']=int(text)
                if not 0<=p['ac']<=100:raise ValueError()
                prompt='❤️ Текущее и максимальное здоровье через пробел.\nНапример: 28 40. У призрака текущее здоровье 0.'
            elif step==1:
                now,maximum=map(int,text.split())
                if not 0<=now<=maximum<=1000000 or maximum<1:raise ValueError()
                p.update(hp_now=now,hp_max=maximum);prompt='👣 Скорость передвижения в футах?\nНапример: 30. Одна клетка карты — 5 футов.'
            elif step==2:
                p['speed_ft']=int(text)
                if not 0<=p['speed_ft']<=1000:raise ValueError()
                prompt='👁 Пассивное Восприятие? Напиши число.\nПри значении 12 противнику нужно 13 или выше для успешной Скрытности.'
            elif step==3:
                p['passive']=int(text)
                if not 0<=p['passive']<=100:raise ValueError()
                prompt='⚔ Оружие героя? Напиши названия и важные свойства. Если нет — «нет».'
            elif step==4:
                if len(text)>1200:raise ValueError()
                p['weapons']=text;prompt='🎒 Багаж героя? До 1200 символов. Если пусто — «нет». Предметы из лавки бот добавит к карточке автоматически.'
            else:
                if len(text)>1200:raise ValueError()
                p['bag']=text
                rid=self.e.char_request(p['target'],p,p.get('editor'))
                self.ui_clear(uid);self.new_request(rid)
                self.send(uid,'🔒 Карточка отправлена мастеру на подтверждение. До одобрения действуют прежние данные.',BACK);return True
        except (ValueError,TypeError):raise RuleError('Проверь значение. Следуй формату из вопроса Роя.')
        self.ui_set(uid,flow,step+1,p);self.ui_prompt(uid,prompt);return True
