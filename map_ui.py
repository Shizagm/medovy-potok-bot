"""Private map navigation, confirmation and nearby visitor pages."""
import json
from map_rules import cell,coord
from interface import kb,BACK
from engine import RuleError

class MapInterfaceMixin:
    def queue_map(self,uid,area=None):
        self.e.player(uid)
        pos=self.e.map_position(uid);area=area or pos['area']
        if area not in self.e.map_data()['floors']:raise RuleError('Неизвестный этаж.')
        self.e.notify(uid,'@MAP@'+json.dumps({'uid':uid,'area':area}))
    def map_photo(self,uid,area):
        from map_render import render_map
        snap=self.e.map_snapshot(uid,area);p=snap['viewer'];f=self.e.map_data()['floors'][p['area']]['name']
        caption=f'🗺 {snap["name"]}\nТы: {f}, {cell(p["x"],p["y"])} · осталось {p["remaining"]} клеток.\nПортрет в фиолетовой рамке — персонаж. Зелёная рамка — ты. Бледный портрет — призрак. Золотой — НПС, красный — монстр.\nКрасное X — закрытая дверь; зелёное O — открытая.'
        if snap['draft']:caption+='\n⚠ Тестовая схема. Геометрия ещё не сверена с настенной картой.'
        for i,lm in enumerate(snap['landmarks'],1):caption+=f'\n{i}: {lm["name"]} · {cell(lm["x"],lm["y"])}'
        if not p['on_map']:caption='🗺 '+snap['name']+'\nГерой ожидает у портала вне карты: свободных клеток не было. Нажми «Войти на карту».\n'+('⚠ Тестовая схема.' if snap['draft'] else '')
        buttons=[[('👣 Переместиться',f'mapmove:{area}'),('👥 Кто рядом','mapnear:0')]] if p['on_map'] else [[('🚪 Войти на карту','mapenter')]]
        buttons.append([('🟣 Портрет жетона','token')])
        for key,lm in self.e.map_data().get('landmarks',{}).items():
            if self.e.map_known(lm['area'],*coord(lm['cell'])):buttons.append([(lm['name'],f'mapgoal:{key}')])
        for npc in snap.get('npcs',[])[:8]:caption+=f'\n{"🔴" if npc["kind"]=="monster" else "🟡"} {npc["name"]} · {cell(npc["x"],npc["y"])}'
        buttons.append([('🗺 Этажи','mapfloors'),('🍯 Меню','home')])
        if len(caption)>950:caption=caption[:947]+'…'
        return render_map(snap),caption,kb(buttons)
    def map_dispatch(self,uid,tail):
        a=tail.split();action=a[0] if a else ''
        if action not in ('map','mapview','mapmove','mapgoal','mappay','mapnear','mapfloors','mapenter'):return False
        self.e.player(uid)
        if action=='mapenter':self.e.map_enter(uid);self.queue_map(uid);return True
        if action in ('map','mapview'):
            self.queue_map(uid,a[1] if len(a)>1 else None);return True
        if action=='mapfloors':
            data=self.e.map_data();rows=[]
            for key,f in data['floors'].items():
                known=any(self.e.map_known(key,x,y,data) for y,row in enumerate(f['rows']) for x in range(len(row)))
                if known:rows.append([(f['name'],f'mapview:{key}')])
            rows.append([('🍯 Меню','home')]);self.send(uid,'🗺 Выбери этаж.',kb(rows));return True
        if action=='mapnear':
            page=int(a[1]) if len(a)>1 else 0
            if page<0:raise RuleError('Неверная страница.')
            rows=[]
            for p in self.e.db.execute('SELECT uid,name,dead FROM players WHERE approved=1 AND uid!=? ORDER BY name',(uid,)).fetchall():
                if self.e.map_adjacent(uid,p['uid']):rows.append(dict(p))
            buttons=[]
            for p in rows[page*12:page*12+12]:
                buttons.append([(p['name']+(' · призрак' if p['dead'] else ''),f'infooffer:{p["uid"]}')])
            nav=[]
            if page:nav.append(('←',f'mapnear:{page-1}'))
            if len(rows)>(page+1)*12:nav.append(('→',f'mapnear:{page+1}'))
            if nav:buttons.append(nav)
            buttons.append([('🗺 Карта','map'),('🍯 Меню','home')])
            text='👥 РЯДОМ С ТОБОЙ\n'+('\n'.join(p['name'] for p in rows[page*12:page*12+12]) if rows else 'Пока никого. Соседство учитывает стены и двери.')+'\n\nКнопка имени открывает предложение сведений Роя за 500 зм. Без подтверждения оплаты нет.'
            self.send(uid,text,kb(buttons));return True
        if action=='mapmove':
            p=self.e.player(uid)
            if p['paused']:raise RuleError('Участие приостановлено.')
            area=a[1] if len(a)>1 else self.e.map_position(uid)['area']
            if area not in self.e.map_data()['floors']:raise RuleError('Неизвестный этаж.')
            self.ui_set(uid,'map_move',payload={'area':area});self.ui_prompt(uid,'👣 Куда идёшь? Укажи клетку латинскими буквами, например L12.\nБот найдёт кратчайший открытый путь. Призрак может лететь через стены, но не открывает туман.');return True
        if action=='mapgoal':
            landmark=self.e.map_data().get('landmarks',{}).get(a[1])
            if not landmark:raise RuleError('Неизвестное место.')
            if not self.e.map_known(landmark['area'],*coord(landmark['cell'])):raise RuleError('Это место пока скрыто.')
            self.map_landmark(uid,landmark);return True
        if action=='mappay':
            result,already=self.e.map_commit(uid,int(a[1]));name=self.e.map_data()['floors'][result['area']]['name']
            self.e.notify(uid,('Это перемещение уже выполнено.' if already else f'👣 {name}, {result["cell"]}. Потрачено {result["cost"]} клеток; осталось {result["remaining"]}.'))
            self.queue_map(uid,result['area']);return True
    def map_landmark(self,uid,landmark):
        target=(landmark['area'],*coord(landmark['cell']));p=self.e.player(uid);pos=self.e.map_position(uid)
        if not pos['on_map']:raise RuleError('Сначала войди на карту.')
        start=(pos['area'],pos['x'],pos['y'])
        if self.e.map_can_stop(uid,target,bool(p['dead'])):self.map_offer(uid,target[0],cell(target[1],target[2]));return
        choices=[]
        for node in self.e.map_neighbors(target,bool(p['dead']),self.e.map_data()):
            if node[0]!=target[0] or not self.e.map_can_stop(uid,node,bool(p['dead'])):continue
            try:path=self.e.map_path(start,node,bool(p['dead']))
            except RuleError:continue
            choices.append((len(path),node))
        if not choices:raise RuleError('У этого места нет доступной свободной клетки.')
        _,node=min(choices)
        if node==start:raise RuleError('Ты уже рядом с этим местом.')
        self.map_offer(uid,node[0],cell(node[1],node[2]))

    def map_offer(self,uid,area,value):
        r=self.e.map_prepare(uid,area,value);end=r['destination'];name=self.e.map_data()['floors'][end[0]]['name']
        text=f'👣 МАРШРУТ\nКуда дойдёшь: {name}, {cell(end[1],end[2])}.\nСтоимость: {r["cost"]} клеток. Останется: {r["remaining"]}.'
        if r['cost']<r['total']:text+=f'\nДо цели {r["total"]} клеток — сейчас пройдёшь только доступную часть маршрута.'
        self.send(uid,text,kb([[('✅ Иду',f'mappay:{r["id"]}'),('Отмена','cancel')],[('🗺 Карта','map')]]))
    def map_answer(self,uid,text,st):
        if st['flow']!='map_move':return False
        self.map_offer(uid,st['payload']['area'],text.strip().upper());self.ui_clear(uid);return True
    def map_command(self,uid,cmd,tail):
        if cmd in ('/map','/move'):
            self.e.player(uid)
            if cmd=='/map':self.queue_map(uid,tail.strip() or None)
            else:
                parts=tail.split();area=parts[0] if len(parts)>1 else self.e.map_position(uid)['area'];value=parts[-1] if parts else ''
                self.map_offer(uid,area,value)
            return True
        known=('/mapmode','/mapgrant','/mapplace','/mapdoor','/mapreveal','/mapload','/mapweekly','/mapadmin')
        if cmd not in known:return False
        self.ui_admin_required(uid);a=tail.split()
        if cmd=='/mapadmin':
            self.send(uid,'🗺 КАРТА · МАСТЕР\n'+('Соседство для сделок: включено' if self.e.map_enabled() else 'Соседство для сделок: выключено')+'\nНедельные ходы: '+('включены' if self.e.meta_value('map_weekly')=='1' else 'выключены')+'\n\n/mapmode 1 — включить проверку соседства; 0 — выключить\n/mapgrant ID — обновить только движение\n/mapplace ID hall L16 — поставить героя\n/mapdoor kitchen 1 — открыть; 0 — закрыть\n/mapreveal cellar B2 H8 — раскрыть прямоугольник\n/mapweekly 1 — автоматический недельный ход всем\n/mapweekly 0 — ручные визиты\n/npcs — НПС, монстры и их жетоны\n/mapload — загрузить приватную схему из data/private-map.json, иначе maps/tavern.json\n\nПрежде чем включать соседство, сверьте тестовую схему с настенной картой.',BACK)
        elif cmd=='/mapmode':self.e.map_enable(int(tail));self.send(uid,'Проверка соседства обновлена.',BACK)
        elif cmd=='/mapgrant':self.e.map_grant(int(tail));self.send(uid,'Запас движения обновлён. Действие не выдано.',BACK)
        elif cmd=='/mapplace':self.e.map_set_position(int(a[0]),a[1],a[2]);self.send(uid,'Герой переставлен.',BACK)
        elif cmd=='/mapdoor':self.e.map_door(a[0],int(a[1]));self.send(uid,'Состояние двери обновлено.',BACK)
        elif cmd=='/mapreveal':self.e.map_reveal(a[0],a[1],a[2]);self.send(uid,'Туман раскрыт.',BACK)
        elif cmd=='/mapload':self.e.map_load();self.send(uid,'Схема загружена; позиции сохранены.',BACK)
        elif cmd=='/mapweekly':
            on=int(tail)
            if on not in (0,1):raise RuleError('Нужно 0 или 1.')
            self.e.db.execute("UPDATE meta SET value=? WHERE key='map_weekly'",(str(on),))
            count=self.e.map_tick() if on else 0
            self.send(uid,f'Недельные ходы: {"включены" if on else "выключены"}. Выдано сейчас: {count}.',BACK)
        return True
