FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd -g 10001 roy && useradd -u 10001 -g roy -m roy
COPY --chown=roy:roy engine.py bot.py games.py tavern.py characters.py interface.py feature_interface.py character_interface.py instance_lock.py ./
COPY --chown=roy:roy assets/ ./assets/
COPY --chown=roy:roy catalog/ ./catalog/
RUN mkdir -p /app/data && chown roy:roy /app/data
# Repair mounted data and resource permissions at runtime, then drop root privileges.
USER root
CMD ["python", "-c", "import os\nfrom pathlib import Path\nimport stat\nimport sys\nroots = (Path('/app/data'), Path('/app/catalog'), Path('/app/assets'))\nfor root in roots:\n    if root.is_symlink():\n        raise SystemExit('Недопустимая символическая ссылка: ' + str(root))\n    if root.name == 'data':\n        root.mkdir(parents=True, exist_ok=True)\n    if os.geteuid() == 0:\n        if not root.is_dir():\n            raise SystemExit('Отсутствует папка: ' + str(root))\n        for base, dirs, files in os.walk(root, followlinks=False):\n            for path in [Path(base)] + [Path(base) / name for name in files]:\n                if path.is_symlink():\n                    continue\n                os.chown(path, 10001, 10001)\n                mode = stat.S_IMODE(path.stat().st_mode)\n                access = 0o700 if path.is_dir() else 0o600 if root.name == 'data' else 0o400\n                os.chmod(path, mode | access)\nif os.geteuid() == 0:\n    os.setgroups([])\n    os.setgid(10001)\n    os.setuid(10001)\nprint('Папки data, catalog и assets доступны. Запуск Роя; UID=' + str(os.geteuid()), flush=True)\nos.execv(sys.executable, [sys.executable, '/app/bot.py'])\n"]
