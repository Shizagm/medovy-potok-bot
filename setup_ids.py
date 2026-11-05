"""Print identifiers from this bot's updates without exposing its token."""
import os
from bot import load_env, Telegram, TelegramError

if __name__=='__main__':
    from pathlib import Path
    os.chdir(Path(__file__).resolve().parent)
    load_env()
    token=os.environ.get('BOT_TOKEN','')
    if not token: raise SystemExit('Сначала заполни BOT_TOKEN в .env')
    try:
        api=Telegram(token)
        if api.call('getWebhookInfo').get('url'):
            raise SystemExit('У бота настроен webhook. Используй нового отдельного бота.')
        updates=api.call('getUpdates',timeout=1,allowed_updates=['message'])
    except TelegramError as exc: raise SystemExit(str(exc)) from None
    found=set()
    for u in updates:
        m=u.get('message',{})
        if not m: continue
        row=(m.get('from',{}).get('id'),m['chat']['id'],m.get('message_thread_id',0))
        if row not in found:
            print(f'Пользователь: {row[0]}; чат: {row[1]}; тема: {row[2]}'); found.add(row)
    if not found: print('Отправь боту /start и /id@имя_бота в группе, затем повтори.')
