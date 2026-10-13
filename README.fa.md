<div dir="rtl">

# IPF3 — مانیتورینگ شبکه و تست کارایی

[English](README.md) | **فارسی**

IPF3 یک پلتفرم خودمیزبان (self-hosted) برای مانیتورینگ مجموعه‌ای از سرورهای اوبونتو و اجرای تست‌های کارایی شبکه بین آن‌هاست. هستهٔ آن **iperf3** است: ایجنت، iperf3 را با خروجی JSON اجرا می‌کند و سرور نتایج را تحلیل و ذخیره می‌کند. داشبورد وب تم تیره (زغالی) با رنگ‌های سبز زمردی دارد.

همهٔ اعداد روی صفحه از اندازه‌گیری واقعی می‌آیند: شمارنده‌های کرنل، `/proc`، iproute2، iperf3، ping، traceroute، mtr یا یک کوئری واقعی DNS. هیچ دادهٔ ساختگی یا درون‌یابی‌شده‌ای نمایش داده نمی‌شود؛ اگر گزارشی نرسد، روی نمودار هم جای خالی می‌ماند.

![داشبورد](docs/images/dashboard.png)

## امکانات

| بخش | توضیح |
|---|---|
| **مصرف لحظه‌ای واقعی** | هر ایجنت هر ۲ ثانیه سرعت فعلی ترافیکی را که واقعاً از سرور عبور می‌کند، از روی شمارنده‌های کرنل گزارش می‌دهد. برای این کار هیچ تستی اجرا نمی‌شود و ترافیک اضافه‌ای ساخته نمی‌شود. |
| **حجم مصرفی روزانه و ماهانه** | دانلود و آپلود هر سرور و کل سرورها برای امروز، این ماه و ۳۰ یا ۹۰ روز اخیر، با نمودار روزانه. فقط کارت‌های شبکهٔ فیزیکی شمرده می‌شوند تا ترافیک docker، wg، tun و bridge دوبار حساب نشود. |
| **مانیتورینگ چند سرور** | CPU، حافظه، swap، دیسک، load، uptime، وضعیت‌های TCP، retransmitها و برای هر اینترفیس: بیت بر ثانیه، پکت بر ثانیه، خطا و drop. هر ۱۰ ثانیه از شمارنده‌های کرنل جمع‌آوری می‌شود. |
| **نمودار لحظه‌ای** | فید زنده با WebSocket برای پهنای باند کل و هر اینترفیس، به‌همراه نمودارهای تاریخی (۱۵ دقیقه تا ۳۰ روز) با بازه‌بندی سمت سرور. |
| **تست سرعت** | iperf3 با TCP/UDP در حالت آپلود، دانلود (`-R`) و دوطرفه؛ با stream موازی، bitrate، omit و IPv6. نمایش throughput هر بازه، retransmit، jitter، packet loss و مصرف CPU. |
| **ابزارهای عیب‌یابی** | Ping (RTT، loss، jitter)، traceroute (UDP/ICMP/TCP)، MTR و DNS (هر نوع رکورد، resolver دلخواه، UDP/TCP، زمان پاسخ). |
| **موجودی سیستم** | اینترفیس‌ها و آدرس‌ها، routeهای IPv4/IPv6، اتصال‌های فعال و تنظیمات DNS. |
| **زمان‌بندی** | تست‌های تکرارشونده برای داده‌های تاریخی و هشدارها. |
| **هشدار** | قانون روی متریک‌های سیستم، اینترفیس، تست‌ها و در دسترس بودن؛ اعلان با webhook (سازگار با Slack) و ایمیل؛ تأیید (ack) و تاریخچه. |
| **تحلیل تاریخی** | روند throughput، RTT (میانگین و p95)، loss و jitter برای هر سرور و مقصد. |
| **امنیت** | نقش‌ها (admin / operator / viewer)، هش رمز argon2id، قفل حساب پس از تلاش ناموفق، محافظت CSRF، لاگ ممیزی، توکن ثبت‌نام یک‌بارمصرف، اعتبارنامهٔ جداگانه و قابل‌ابطال برای هر ایجنت، TLS و سرویس‌های systemd با حداقل دسترسی. |
| **عملیات** | نصب با یک دستور روی اوبونتو، migration دیتابیس، اسکریپت ارتقا، بکاپ روزانهٔ تأییدشده، بازیابی و حذف خودکار دادهٔ قدیمی. |

## معماری

</div>

```
 Browser ──HTTPS/WSS──► nginx ──► uvicorn (FastAPI) ──► PostgreSQL
                         │                ▲                 ▲
                         └─ React UI      │                 │
                                          │         ipf3-worker (schedules,
 Ubuntu host                              │         alerts, retention)
 ┌──────────────────────────────┐ HTTPS   │
 │ ipf3-agent (unprivileged,    │─────────┘  outbound only
 │ CAP_NET_RAW only)            │
 │  └─ iperf3 · ping · traceroute · mtr · DNS
 │ ipf3-iperf3 (optional iperf3 -s)
 └──────────────────────────────┘
```

<div dir="rtl">

ایجنت‌ها هیچ اتصال ورودی از سرور قبول نمی‌کنند؛ خودشان از طریق HTTPS کارها (job) را دریافت می‌کنند و خروجی خام ابزار را گزارش می‌دهند.

## پیش‌نیازها

- **Ubuntu 22.04 LTS یا 24.04 LTS** (x86_64 یا arm64) برای سرور اصلی و ایجنت‌ها
- یک نام دامنه که به سرور اصلی اشاره کند (برای Let's Encrypt)، یا گواهی خودتان، یا گواهی self-signed
- پورت ورودی TCP 443 روی سرور اصلی (و 80 فقط برای Let's Encrypt)
- دسترسی root (sudo)

## نصب

### ۱. نصب سرور اصلی (کنترل‌پنل)

</div>

```bash
# دریافت کد
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/amirali272/ipf3.git
cd ipf3

# نصب با گواهی Let's Encrypt (دامنه باید به این سرور اشاره کند)
sudo ./deploy/install-server.sh --domain ipf3.example.com --tls letsencrypt --email ops@example.com
```

<div dir="rtl">

روش‌های دیگر TLS:

</div>

```bash
# گواهی self-signed (مثلاً وقتی فقط IP دارید)
sudo ./deploy/install-server.sh --domain 10.0.0.5 --tls self-signed

# گواهی موجود خودتان
sudo ./deploy/install-server.sh --domain ipf3.corp --tls existing \
     --cert /path/fullchain.pem --key /path/privkey.pem

# فعال‌کردن فایروال ufw (باز کردن SSH و 80 و 443)
sudo ./deploy/install-server.sh --domain ipf3.example.com --tls letsencrypt --email ops@example.com --ufw
```

<div dir="rtl">

| گزینه | توضیح |
|---|---|
| `--domain` | نام دامنه یا IP سرور (الزامی) |
| `--tls` | `letsencrypt` یا `self-signed` یا `existing` (پیش‌فرض: self-signed) |
| `--email` | ایمیل برای Let's Encrypt |
| `--cert` / `--key` | مسیر گواهی و کلید برای حالت `existing` |
| `--admin-user` | نام کاربر مدیر اولیه (پیش‌فرض `admin`) |
| `--workers` | تعداد پروسس‌های API (پیش‌فرض ۲) |
| `--ufw` | فعال‌سازی فایروال و باز کردن پورت‌های لازم |
| `--skip-web-build` | استفاده از `web/dist` آماده، بدون نیاز به Node.js |

اسکریپت PostgreSQL، nginx، API، worker و رابط وب را نصب می‌کند و در پایان **رمز عبور مدیر را فقط یک بار** چاپ می‌کند. آن را یادداشت کنید و بعد از اولین ورود، از بخش **Account** تغییر دهید.

بررسی سلامت سرور:

</div>

```bash
systemctl status ipf3-api ipf3-worker
curl -fsS https://ipf3.example.com/healthz
```

<div dir="rtl">

### ۲. نصب ایجنت روی هر سرور

۱. در رابط وب وارد شوید و به **Servers ← Enroll server** بروید و یک توکن بسازید (یک‌بارمصرف است و ۲۴ ساعت اعتبار دارد).

۲. روی سروری که می‌خواهید مانیتور شود اجرا کنید:

</div>

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/amirali272/ipf3.git
cd ipf3

sudo ./deploy/install-agent.sh \
  --server https://ipf3.example.com \
  --token ipf3e_XXXXXXXXXXXX \
  --name server-1 \
  --iperf3-server
```

<div dir="rtl">

| گزینه | توضیح |
|---|---|
| `--server` | آدرس HTTPS سرور اصلی (الزامی) |
| `--token` | توکن ثبت‌نام از رابط وب (الزامی) |
| `--name` | نام ایجنت (پیش‌فرض: hostname) |
| `--iperf3-server` | اجرای یک سرور iperf3 روی این میزبان تا سرورهای دیگر بتوانند تست سرعت به آن بزنند |
| `--iperf3-port` | پورت iperf3 (پیش‌فرض 5201) |
| `--ca-file` | اگر سرور اصلی گواهی self-signed دارد، فایل `/etc/ipf3/tls/server.crt` سرور اصلی را اینجا کپی و معرفی کنید |
| `--reenroll` | ثبت‌نام مجدد با توکن جدید |

اگر سرور اصلی self-signed است، ابتدا گواهی را کپی کنید:

</div>

```bash
# روی سرور ایجنت
scp root@ipf3-server:/etc/ipf3/tls/server.crt ./server.crt
sudo ./deploy/install-agent.sh --server https://10.0.0.5 --token ipf3e_XXXX --ca-file ./server.crt --iperf3-server
```

<div dir="rtl">

بررسی ایجنت:

</div>

```bash
systemctl status ipf3-agent
journalctl -u ipf3-agent -f
sudo -u ipf3-agent /opt/ipf3-agent/venv/bin/ipf3-agent check
```

<div dir="rtl">

بعد از حدود ۱۰ ثانیه سرور در رابط وب **Online** می‌شود و نمودارها پر می‌شوند.

### ۳. محدود کردن دسترسی به iperf3

iperf3 به‌صورت پیش‌فرض احراز هویت ندارد. پورت آن را (TCP و UDP) فقط برای سرورهایی که تست می‌زنند باز کنید:

</div>

```bash
sudo ufw allow from 10.20.0.0/16 to any port 5201 proto tcp
sudo ufw allow from 10.20.0.0/16 to any port 5201 proto udp
```

<div dir="rtl">

## ارتقا (Upgrade)

</div>

```bash
# سرور اصلی (قبل از ارتقا به‌صورت خودکار بکاپ گرفته می‌شود)
cd ipf3 && git pull
sudo ./deploy/upgrade-server.sh

# هر ایجنت
cd ipf3 && git pull
sudo ./deploy/upgrade-agent.sh
```

<div dir="rtl">

## بکاپ و بازیابی

بکاپ هر شب به‌صورت خودکار در `/var/backups/ipf3` گرفته می‌شود (۱۴ روز نگهداری). حتماً از این پوشه یک کپی خارج از سرور نگه دارید.

</div>

```bash
# بکاپ دستی
sudo /opt/ipf3/deploy/backup.sh

# بازیابی
sudo ./deploy/restore.sh /var/backups/ipf3/ipf3-db-<تاریخ>.dump \
     --config /var/backups/ipf3/ipf3-config-<تاریخ>.tar.gz
```

<div dir="rtl">

## حذف ایجنت

</div>

```bash
sudo ./deploy/uninstall-agent.sh
```

<div dir="rtl">

سپس سرور را از **Servers ← (نام سرور) ← Settings** در رابط وب حذف کنید.

## رفع مشکلات رایج

| مشکل | راه‌حل |
|---|---|
| سرور **Offline** است | `journalctl -u ipf3-agent` را ببینید. خطای TLS یعنی `--ca-file` لازم است؛ خطای 401 یعنی اعتبارنامه باطل شده و باید با `--reenroll` دوباره ثبت‌نام کنید. |
| تست iperf3 با خطای «unable to connect» | روی مقصد `systemctl status ipf3-iperf3` را چک کنید و فایروال (TCP و برای UDP، UDP) را باز کنید. |
| «the server is busy running a test» | هر سرور iperf3 در هر لحظه فقط یک تست را می‌پذیرد؛ زمان‌بندی‌ها را با فاصله تنظیم کنید. |
| رمز مدیر را فراموش کرده‌اید | `sudo -u ipf3 bash -c 'set -a; . /etc/ipf3/server.env; set +a; /opt/ipf3/venv/bin/ipf3-server create-user admin --role admin --update'` |

## مستندات بیشتر (انگلیسی)

- [نصب و TLS](docs/INSTALL.md)
- [مرجع تنظیمات](docs/CONFIGURATION.md)
- [مدل امنیتی](docs/SECURITY.md)
- [عملیات: ارتقا، بکاپ، بازیابی](docs/OPERATIONS.md)
- [API و پروتکل ایجنت](docs/API.md)
- [معماری](docs/ARCHITECTURE.md)
- [توسعه](docs/DEVELOPMENT.md)

## ساختار مخزن

</div>

```
server/   FastAPI backend + migrations + tests
agent/    ipf3-agent + tests
web/      React + TypeScript dashboard
deploy/   systemd units, nginx, install / upgrade / backup / restore scripts
docs/     documentation
```
