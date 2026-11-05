"""Developer-only refresh of public item names/rarities/URLs; no rules text copied."""
from datetime import date
import json
from pathlib import Path
import re
import urllib.request

URL='https://next.dnd.su/items/'
RARITIES={6:'common',1:'uncommon',2:'rare',3:'very_rare',4:'legendary'}
if __name__=='__main__':
    page=urllib.request.urlopen(URL,timeout=30).read(3000000).decode('utf-8')
    match=re.search(r'window\.LIST\s*=\s*',page)
    if not match:raise SystemExit('Структура страницы изменилась: каталог не обновлён.')
    data,_=json.JSONDecoder().raw_decode(page[match.end():])
    items=[];seen=set()
    for card in data['cards']:
        rarities=card.get('filter_rarity',[])
        if len(rarities)!=1 or rarities[0] not in RARITIES:continue
        match=re.fullmatch(r'/items/(\d+)-[^?#]+/?',card['link'])
        if not match:continue
        iid=int(match.group(1))
        if iid in seen:continue
        seen.add(iid)
        items.append(dict(id=iid,name=card['title'],rarity=RARITIES[rarities[0]],type=card['item_icon_title'],url=URL.rstrip('/')+'/'+card['link'].split('/items/',1)[1].rstrip('/')+'/'))
    if not items:raise SystemExit('Список пуст: старый каталог сохранён.')
    path=Path(__file__).resolve().parent.parent/'catalog/items.json'
    value=dict(source=URL,edition='Каталог next.dnd.su / 5e24; включает совместимые материалы',retrieved=str(date.today()),items=items)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    print(f'Обновлены метаданные {len(items)} предметов. Проверьте список перед выпуском обновления.')
