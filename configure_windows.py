"""Interactive local setup. Never puts the bot token in command-line arguments."""
import getpass
import os
from pathlib import Path
import re
from bot import Telegram, TelegramError

BASE=Path(__file__).resolve().parent

def read_values(path):
    values={}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1); values[key.strip()]=value.strip().strip('"').strip("'")
    return values

def save(values):
    # Values are data, never shell code. Atomic replacement preserves old config on error.
    path=BASE/'.env'; temp=BASE/'.env.tmp'
    with open(temp,'w',encoding='utf-8',newline='\n') as f:
        for key in ('BOT_TOKEN','ADMIN_IDS','TAVERN_CHAT_ID','PUBLIC_TOPIC_ID','DB_PATH','BACKUP_DIR'):
            value=values.get(key,'')
            if '\n' in value or '\r' in value: raise ValueError('Недопустимый перенос строки.')
            f.write(key+'='+value+'\n')
    try: temp.chmod(0o600)
    except OSError: pass
    os.replace(temp,path)

def number(prompt,default='',negative=False):
    while True:
        value=input(prompt+(f' [{default}]' if default else '')+': ').strip() or str(default)
        try:
            n=int(value)
            if (negative and n>=0) or (not negative and n<=0): raise ValueError()
            return str(n)
        except ValueError: print('Введите числовой ID '+('с минусом.' if negative else 'больше нуля.'))

def main():
    os.chdir(BASE)
    print('МЕДОВЫЙ ПОТОК — настройка бота Роя для Windows\n')
    print('Сначала откройте бота в Telegram и нажмите «Запустить».')
    print('Добавьте бота администратором в отдельную закрытую группу.')
    print('В группе отправьте /id@username_вашего_бота. Программа пока не отвечает — это нормально.\n')
    values=read_values(BASE/'.env')
    token=getpass.getpass('Вставьте токен BotFather (ввод скрыт; Enter сохраняет существующий): ').strip() or values.get('BOT_TOKEN','')
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+',token):
        print('Токен имеет неверный формат. Настройки не изменены.'); return 1
    values.update(BOT_TOKEN=token)
    values.setdefault('PUBLIC_TOPIC_ID','0'); values.setdefault('DB_PATH','data/tavern.sqlite3'); values.setdefault('BACKUP_DIR','data/backups')
    api=Telegram(token)
    try:
        me=api.call('getMe'); print('Соединение с Telegram установлено. Бот: @'+me['username'])
        if api.call('getWebhookInfo').get('url'):
            print('У этого бота настроен webhook. Не меняем его: используйте отдельного бота.'); return 1
        input('Проверьте, что отправили /start боту и /id@'+me['username']+' в группе. Затем нажмите Enter...')
        updates=api.call('getUpdates',timeout=2,allowed_updates=['message'])
        users={}; groups={}
        for u in updates:
            msg=u.get('message',{}); sender=msg.get('from',{}); chat=msg.get('chat',{})
            if sender and not sender.get('is_bot'): users[sender['id']]=sender.get('first_name','')
            if chat.get('id',0)<0: groups[chat['id']]=chat.get('title','Группа')
        print('\nОбнаруженные пользователи (выберите себя):')
        for uid,name in users.items(): print(f'  {uid} — {name}')
        print('Обнаруженные группы:')
        for gid,title in groups.items(): print(f'  {gid} — {title}')
        admin_default=values.get('ADMIN_IDS','').split(',')[0]
        if not admin_default and len(users)==1: admin_default=str(next(iter(users)))
        group_default=values.get('TAVERN_CHAT_ID','')
        if not group_default and len(groups)==1: group_default=str(next(iter(groups)))
        if not users or not groups:
            print('Если нужных ID нет, прервите настройку Ctrl+C, отправьте новые команды в Telegram и запустите снова.')
        admin=number('Ваш ID мастера',admin_default)
        group=number('ID закрытой группы',group_default,negative=True)
        chat=api.call('getChat',chat_id=int(group))
        member=api.call('getChatMember',chat_id=int(group),user_id=me['id'])
        if member['status']!='administrator':
            print('Бот ещё не администратор группы. Выдайте права и повторите настройку.'); return 1
        owner=api.call('getChatMember',chat_id=int(group),user_id=int(admin))
        if owner['status'] not in ('administrator','creator'):
            print('Указанный мастер не администратор этой группы. Проверьте ID.'); return 1
        print(f'\nБот: @{me["username"]}\nГруппа: {chat.get("title",group)}\nМастер: {admin}')
        if input('Сохранить эти настройки? Введите да: ').strip().lower() not in ('да','yes'):
            print('Настройки не изменены.'); return 1
        values.update(ADMIN_IDS=admin,TAVERN_CHAT_ID=group)
        save(values)
        print('\nНастройки сохранены в .env. Токен не отображается.')
        print('Теперь запустите START_BOT.bat. Окно бота оставляйте открытым.')
        return 0
    except TelegramError as exc:
        print('Ошибка соединения с Telegram: '+str(exc))
        print('Проверка curl прошла, но соединение из Python может отличаться. Сообщите эту ошибку без токена.')
        return 1

if __name__=='__main__':
    try: raise SystemExit(main())
    except KeyboardInterrupt: print('\nНастройка прервана. Сохранённые настройки не изменены.')
