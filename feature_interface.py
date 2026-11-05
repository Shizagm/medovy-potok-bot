"""Menus for Roy's purse, the item shop, and an optional club support display."""
import json
import secrets
from engine import RuleError
from interface import kb,money,BACK
from tavern import RARITIES

class FeatureInterfaceMixin:
    def feature_ui(self,uid,tail):
        args=tail.split();action=args[0] if args else ''
        public={'shop','shopoffer','shopbuy','shopcancel','shoplist','roy','royattempt','support'}
        admin={'features','royedit','royconfirm','royresolve','shopmanage','shopprice','catalogsearch','catalogtoggle','supportadmin','supporttoggle','supportedit','supportconfirm'}
        if action not in public|admin:return False
        if action in admin:self.ui_admin_required(uid)
        else:
            self.e.player(uid)
            if action in ('shop','shopoffer','shoplist','roy','royattempt'):self.e.require_alive(uid)
        if action=='shop':
            rows=[];lines=['🎁 ЛАВКА РОЯ','\nВыбери редкость — достану один случайный предмет с этой полки.']
            for rarity,label in RARITIES.items():
                price=self.e.shop_price(rarity);count=len(self.e.shop_pool(rarity))
                if price['enabled'] and count:rows.append([(f'{label} · {money(price["price"])} зм',f'shopoffer:{rarity}')])
            lines.append('\nНазвания и ссылки — из каталога next.dnd.su.\nОплата только игровым золотом. Плата за сам выбор, дубликаты возможны.')
            rows.append([('🍯 К стойке Роя','home')]);self.send(uid,'\n'.join(lines),kb(rows));return True
        if action=='shopoffer':
            order=self.e.shop_prepare(uid,args[1]);label=RARITIES[order['rarity']]
            self.send(uid,f'🎁 ЗАКАЗ РОЮ №{order["id"]}\n\nРедкость: {label}\nЦена: {money(order["price"])} зм\nВозможных предметов: {order["count"]}\n\nКаждый предмет в списке имеет одинаковый шанс. Повтор уже имеющегося предмета возможен. Сначала платит кошелёк, затем сундук.\n\nПосле подтверждения предмет сразу появится у героя. Правила предмета — по ссылке в результате.',kb([[('🎁 Купить за '+money(order['price'])+' зм',f'shopbuy:{order["id"]}')],[('📜 Посмотреть состав полки',f'shoplist:{order["rarity"]}:0')],[('Отказаться',f'shopcancel:{order["id"]}')]]));return True
        if action=='shopcancel':self.e.shop_cancel(int(args[1]),uid);self.send(uid,'🎁 Заказ отменён. Монеты остались у тебя.',kb([[('🎁 К полкам','shop')],[('🍯 Меню','home')]]));return True
        if action=='shopbuy':
            result=self.e.shop_buy(int(args[1]),uid);item=result['item'];order=result['order']
            msg=f'🎁 НАХОДКА ИЗ ЛАВКИ РОЯ\n\n{self.e.player(uid)["name"]} получил: {item["name"]}\nРедкость: {RARITIES[item["rarity"]]}\nЦена: {money(order["price"])} зм\nПредмет №{item["id"]}\n\n{item["source_url"]}'
            if result['already']:self.send(uid,'Этот заказ уже исполнен.\n\n'+msg,BACK)
            else:
                self.e.notify(self.group,'🎁 НАХОДКА ИЗ ЛАВКИ РОЯ\n\n'+self.e.player(uid)['name']+' получил предмет. Подробности хранятся в закрытой карточке героя.')
                self.queue_card(uid,msg,kb([[('🎒 Мой герой','hero'),('🎁 Лавка','shop')],[('🍯 Меню','home')]]),f'shop_result:{order["id"]}')
            return True
        if action=='shoplist':
            rarity=args[1];page=max(0,int(args[2]));pool=self.e.shop_pool(rarity);size=15
            pages=max(1,(len(pool)+size-1)//size);page=min(page,pages-1)
            text=f'📜 ПОЛКА: {RARITIES[rarity]}\nСтраница {page+1}/{pages}\n\n'
            text+='\n'.join(f'{page*size+i}. {item["name"]}' for i,item in enumerate(pool[page*size:(page+1)*size],1))
            rows=[];nav=[]
            if page:nav.append(('← Назад',f'shoplist:{rarity}:{page-1}'))
            if page+1<pages:nav.append(('Дальше →',f'shoplist:{rarity}:{page+1}'))
            if nav:rows.append(nav)
            rows.append([('🎁 К полкам','shop')]);self.send(uid,text,kb(rows));return True
        if action=='roy':
            text=f'🍯 КОШЕЛЁК РОЯ\n\nВ кармане хозяина: {money(self.e.royal_gold())} зм.\nЭто игровое золото таверны.\n\nМожно попробовать стащить монеты: одна попытка за визит, за действие. Мастер проверяет положение на карте и назначает модификаторы.\nУспешная добыча — до 10% кошелька, максимум 50 зм; при малом остатке минимум 1 зм.'
            self.send(uid,text,kb([[('🖐 Попытаться за основное действие','royattempt:base')],[('✨ Попытаться за Вдохновение','royattempt:inspiration')],[('🍯 Меню','home')]]));return True
        if action=='royattempt':
            resource=args[1]
            if resource not in ('base','inspiration'):raise RuleError('Неизвестное действие.')
            p=self.e.player(uid)
            if self.e.royal_gold()<=0:raise RuleError('Кошелёк Роя пока пуст.')
            if not p['visit']:raise RuleError('Сначала мастер должен выдать ход за визит.')
            rid=self.e.request(uid,'roy_theft',{'resource':resource,'text':'Пытаюсь обворовать Роя'})
            self.new_request(rid);return True
        if action=='support':
            if self.e.meta_value('support_enabled','0')!='1':self.send(uid,'Копилка клуба пока не опубликована.',BACK);return True
            balance=int(self.e.meta_value('support_balance_rub','0'))
            text='🔥 КОПИЛКА «ФЕНИКСА»\nРеальные рубли · добровольная поддержка\n\n'
            text+='Цель: '+self.e.meta_value('support_goal','Работа сервера и поддержание клуба «Феникс»')+'\n'
            text+=f'Остаток по записям Ивана: {money(balance)} ₽\nОбновлено: {self.e.meta_value("support_updated","—")}\n\n'
            report=self.e.meta_value('support_report','Отчёт о поступлениях и расходах ещё не добавлен.')
            text+='Отчёт\n'+report+'\n\nСумму обновляет Иван вручную. Поддержка не выдаёт игровое золото, предметы или Вдохновение.'
            buttons=BACK;url=self.e.meta_value('support_url')
            if url:buttons={'inline_keyboard':[[{'text':'🔥 Поддержать клуб','url':url}],[{'text':'🍯 К стойке Роя','callback_data':'ui:home'}]]}
            self.send(uid,text,buttons);return True
        if action=='features':
            self.send(uid,'🗝 ТАВЕРНА И ЛАВКА\n\nИгровой кошелёк Роя и реальная копилка клуба учитываются отдельно.',kb([[('🍯 Золото Роя','royedit'),('🎁 Настроить лавку','shopmanage')],[('🔥 Копилка клуба','supportadmin')],[('🗝 Меню мастера','admin')]]));return True
        if action=='royedit':
            self.ui_set(uid,'roy_gold');self.ui_prompt(uid,f'🍯 КОШЕЛЁК РОЯ\nСейчас: {self.e.royal_gold()} зм.\nКакой точный остаток установить? Это только игровое золото.');return True
        if action=='royconfirm':
            st=self.ui_state(uid)
            if not st or st['flow']!='roy_confirm' or len(args)<2 or args[1]!=st['payload']['nonce']:raise RuleError('Это подтверждение уже неактуально.')
            p=st['payload'];new=self.e.roy_adjust(uid,p['amount'],p['reason'])
            self.ui_clear(uid);self.send(uid,f'🍯 В кошельке Роя теперь {money(new)} зм.',kb([[('🗝 Таверна и лавка','features')]]));return True
        if action=='royresolve':
            rid=int(args[1]);r=self.e.req(rid)
            if r['kind']!='roy_theft' or r['status']!='pending':raise RuleError('Попытка уже закрыта или не относится к Рою.')
            self.ui_set(uid,'roy_resolve',payload={'rid':rid})
            self.ui_prompt(uid,'🎲 ПРОВЕРКИ У РОЯ\n\nНапиши четыре числа через пробел:\nСкрытность героя, Ловкость рук героя, Внимательность Роя, сложность кражи.\n\nНапример: 5 7 2 14\nДля попытки без Скрытности: none 7 2 14\nЭто модификаторы, а не готовые броски.');return True
        if action=='shopmanage':
            rows=[]
            for rarity,label in RARITIES.items():
                p=self.e.shop_price(rarity);text=label+' · '+(str(p['price'])+' зм' if p['enabled'] else 'закрыта')
                rows.append([(text,f'shopprice:{rarity}')])
            rows.extend([[('🔎 Включить / исключить предмет','catalogsearch')],[('🗝 Таверна и лавка','features')]])
            self.send(uid,'🎁 ЦЕНЫ ЛАВКИ\n\nВыбери редкость. Цена 0 закрывает полку.',kb(rows));return True
        if action=='shopprice':
            if args[1] not in RARITIES:raise RuleError('Неизвестная редкость.')
            self.ui_set(uid,'shop_price',payload={'rarity':args[1]});self.ui_prompt(uid,'🎁 '+RARITIES[args[1]]+'\nКакую цену установить в игровых зм? 0 — закрыть полку.');return True
        if action=='catalogsearch':self.ui_set(uid,'catalog_search');self.ui_prompt(uid,'🔎 Напиши часть названия предмета из каталога next.dnd.su.');return True
        if action=='catalogtoggle':
            cid=int(args[1]);self.e.shop_toggle(cid)
            r=self.e.db.execute('SELECT * FROM shop_catalog WHERE id=?',(cid,)).fetchone()
            self.send(uid,r['name']+'\n'+('🟢 Включён в случайную выдачу.' if r['enabled'] else '⛔ Исключён из случайной выдачи.'),kb([[('🔎 Найти другой предмет','catalogsearch')],[('🎁 Настройки лавки','shopmanage')]]));return True
        if action=='supportadmin':
            enabled=self.e.meta_value('support_enabled','0')=='1'
            self.send(uid,'🔥 КОПИЛКА КЛУБА\n\nСтраница '+('видна участникам' if enabled else 'скрыта')+'.\nРублёвый остаток — ручная запись, не банковская выписка. Игровые операции его не меняют.',kb([[('Скрыть страницу' if enabled else 'Показать участникам',f'supporttoggle:{0 if enabled else 1}')],[('🪙 Остаток в рублях','supportedit:balance'),('🎯 Цель','supportedit:goal')],[('📒 Отчёт','supportedit:report'),('🔗 Ссылка для поддержки','supportedit:url')],[('🗝 Таверна и лавка','features')]]));return True
        if action=='supporttoggle':self.e.support_update(uid,'support_enabled',args[1]);self.send(uid,'Видимость копилки обновлена.',kb([[('🔥 Настройки копилки','supportadmin')]]));return True
        if action=='supportedit':
            field=args[1]
            if field not in ('balance','goal','report','url'):raise RuleError('Неизвестное поле.')
            self.ui_set(uid,'support_edit',payload={'field':field})
            prompts={'balance':'Какой точный остаток целевого фонда в реальных рублях? Целое число.','goal':'На что собираются средства? Напиши цель.','report':'Пришли краткий отчёт: поступления, расходы, даты. До 2500 символов.','url':'Пришли HTTPS-ссылку для добровольной поддержки. Дефис — убрать ссылку.'}
            self.ui_prompt(uid,'🔥 КОПИЛКА КЛУБА\n\n'+prompts[field]);return True
        if action=='supportconfirm':
            st=self.ui_state(uid)
            if not st or st['flow']!='support_confirm' or len(args)<2 or args[1]!=st['payload']['nonce']:raise RuleError('Это подтверждение уже неактуально.')
            p=st['payload'];self.e.support_update(uid,'support_balance_rub',str(p['amount']),p['reason'])
            self.ui_clear(uid);self.send(uid,'🔥 Рублёвый остаток записан.',kb([[('🔥 Копилка клуба','supportadmin')]]));return True
        return False

    def feature_answer(self,uid,text,st):
        flow=st['flow'];p=st['payload'];step=st['step']
        if flow not in ('roy_gold','roy_confirm','roy_resolve','shop_price','catalog_search','support_edit','support_confirm'):return False
        self.ui_admin_required(uid)
        if flow in ('roy_confirm','support_confirm'):raise RuleError('Используй кнопку подтверждения или отмени ввод.')
        if flow=='roy_resolve':
            parts=text.split()
            if len(parts)!=4:raise RuleError('Нужны три модификатора и сложность: например, 5 7 2 14.')
            try:stealth=None if parts[0].lower()=='none' else int(parts[0]);hands,perception,dc=map(int,parts[1:])
            except ValueError:raise RuleError('Проверь числа модификаторов.')
            result=self.e.roy_resolve(p['rid'],stealth,hands,perception,dc)
            self.ui_clear(uid);self.refresh_request(p['rid']);self.feature_roy_result(p['rid'],result)
            return True
        if flow=='catalog_search':
            if len(text)>100:raise RuleError('Сократи поисковую строку.')
            # SQLite lower() is ASCII-only; Unicode matching is done on the catalog in Python.
            rows=[r for r in self.e.db.execute('SELECT * FROM shop_catalog ORDER BY name') if text.casefold() in r['name'].casefold()][:20]
            self.ui_clear(uid);buttons=[[(('🟢 ' if r['enabled'] else '⛔ ')+r['name'][:48],f'catalogtoggle:{r["id"]}')] for r in rows]
            buttons.append([('🎁 Настройки лавки','shopmanage')]);self.send(uid,'🔎 Найденные предметы\nНажатие меняет доступность.' if rows else 'Совпадений нет.',kb(buttons));return True
        if flow=='shop_price':
            try:price=int(text.replace(' ',''))
            except ValueError:raise RuleError('Нужна целая цена в игровых зм.')
            self.e.shop_set_price(p['rarity'],price);self.ui_clear(uid);self.send(uid,'🎁 Цена полки обновлена.',kb([[('🎁 Настройки лавки','shopmanage')]]));return True
        if flow=='roy_gold':
            if step==0:
                try:n=int(text.replace(' ',''))
                except ValueError:raise RuleError('Нужна целая сумма игрового золота.')
                if not 0<=n<=1000000000:raise RuleError('Проверь сумму.')
                self.ui_set(uid,flow,1,{'amount':n});self.ui_prompt(uid,'📒 Причина изменения игрового кошелька Роя?');return True
            p.update(reason=text,nonce=secrets.token_hex(4));self.ui_set(uid,'roy_confirm',payload=p)
            self.send(uid,f'🍯 Установить Рою {money(p["amount"])} игровых зм?\nПричина: {text}',kb([[('✅ Подтвердить',f'royconfirm:{p["nonce"]}'),('Отменить','cancel')]]));return True
        if flow=='support_edit':
            field=p['field']
            if field=='balance':
                if step==0:
                    try:n=int(text.replace(' ',''))
                    except ValueError:raise RuleError('Нужна целая сумма реальных рублей.')
                    if not 0<=n<=1000000000:raise RuleError('Проверь сумму.')
                    self.ui_set(uid,flow,1,{'field':field,'amount':n});self.ui_prompt(uid,'📒 Причина изменения рублёвого остатка?');return True
                p.update(reason=text,nonce=secrets.token_hex(4));self.ui_set(uid,'support_confirm',payload=p)
                self.send(uid,f'🔥 Установить остаток копилки {money(p["amount"])} ₽?\nПричина: {text}',kb([[('✅ Подтвердить',f'supportconfirm:{p["nonce"]}'),('Отменить','cancel')]]));return True
            if field=='report' and len(text)>2500:raise RuleError('Отчёт — до 2500 символов.')
            key={'goal':'support_goal','report':'support_report','url':'support_url'}[field]
            self.e.support_update(uid,key,'' if field=='url' and text=='-' else text)
            self.ui_clear(uid);self.send(uid,'🔥 Копилка обновлена.',kb([[('🔥 Настройки копилки','supportadmin')]]));return True
        return False

    def feature_roy_result(self,rid,result):
        r=self.e.req(rid);name=self.e.player(r['a'])['name']
        details='🍯 ПРОВЕРКА У РОЯ №'+str(rid)+'\n'+json.dumps(result,ensure_ascii=False)
        for admin in self.admins:self.e.notify(admin,details)
        if r['payload']['resource']=='inspiration':self.e.notify(self.group,f'✨ {name} использовал Вдохновение Роя и получает дополнительное действие.')
        if result['detected']:
            self.e.notify(self.group,f'🍯 Рой поймал взглядом {name}. '+(f'Из кошелька успели исчезнуть {result["amount"]} зм.' if result['success'] else 'Монеты остались на месте.'))
        elif result['success']:self.e.notify(self.group,f'🍯 Рой пересчитал монеты: пропало {result["amount"]} зм. Кто-то оказался ловчее хозяина.')
