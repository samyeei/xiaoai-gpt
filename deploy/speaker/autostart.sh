#!/bin/sh
set -eu
test -x /data/open-xiaoai/client || { echo 'Client is missing; run and verify init.sh first.'; exit 1; }
test -f /data/open-xiaoai/server.txt
if [ -f /data/init.sh ]; then
  if grep -q '# xiaoai-muse-autostart$' /data/init.sh; then
    echo 'Autostart already configured.'; exit 0
  fi
  # Do not append after an unconditional exit or replace another project's init.
  if grep -Eq '^[[:space:]]*(exit|exec)[[:space:]]' /data/init.sh; then
    echo 'Existing init.sh contains exit/exec; manual merge is needed.'; exit 1
  fi
  cp -p /data/init.sh /data/init.sh.before-muse
else
  printf '%s\n' '#!/bin/sh' > /data/init.sh
fi
printf '\n%s\n' 'sh /data/open-xiaoai/init.sh >/tmp/open-xiaoai.log 2>&1 & # xiaoai-muse-autostart' >> /data/init.sh
chmod +x /data/init.sh
echo 'Autostart appended; reboot only after finishing your current tests.'
