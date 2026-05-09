=== systemctl services VQ-related (full) ===

Snapshot: 2026-05-09T07:15:57Z

## All VQ services
```
  bot2_prime.service                       loaded    active     running            Bot2 Prime Trading Bot (Marco)
  bot3_prime.service                       loaded    active     running            Bot3 Prime Trading Bot
  bot3_prime_bitunix_git_backup.service    loaded    inactive   dead               Push bot3_prime_bitunix to Gitea (primary) + Newark (backup emergencia)
  bot3_prime_git_backup.service            loaded    inactive   dead               Push bot3_prime to Gitea (primary) + Newark (backup emergencia)
  cafecito.service                         loaded    inactive   dead               Cafecito de la Mañana — Video pipeline diario ProfitLab
  hftbots-evaluator.service                loaded    inactive   dead               HFT Bots performance evaluator (one-shot)
  hftbots-pair-scanner.service             loaded    inactive   dead               HFT Bots — Dynamic Pair Scanner (Long-Tail MEV)
  poly_log_rotator.service                 loaded    inactive   dead               VelocityQuant Polymarket Sidecar log rotator (P5.0)
  profitlab_prime.service                  loaded    active     running            ProfitLab Prime Trading Bot
  profitlab_prime_bitunix.service          loaded    active     running            ProfitLab Prime Bitunix Bot
  profitlab_prime_panel.service            loaded    inactive   dead               ProfitLab Prime — Panel Web (modo lectura, siempre activo)
  profitlab_quantum_bot.service            loaded    active     running            ProfitLab Quantum Bot (Paper Trading)
  profitlab_quantum_web.service            loaded    active     running            ProfitLab Quantum Web Panel (FastAPI/Uvicorn)
  quantum_dashboard.service                loaded    active     running            Quantum Dashboard Service
● trading_bot.service                      loaded    failed     failed             Trading Bot Service
● velocityquant-pathc-healthcheck.service  loaded    failed     failed             VelocityQuant Path C Health Check (R74 V2.1)
  velocityquant-refill-sol.service         loaded    inactive   dead               VelocityQuant Auto-refill SOL gas (every 15 min, GaL85 → hot200 4V6f2c3G)
  velocityquant-refill-x402.service        loaded    inactive   dead               VelocityQuant Auto-refill x402 USDC (every 15 min, GaL85 → 8BZjAp51)
  velocityquant-shadow-collector.service   loaded    activating start        start VelocityQuant Shadow Run Telemetry Collector
  velocityquant-v21-autoreport.service     loaded    inactive   dead               VelocityQuant R74 V2.1 Auto Report Generator (one-shot at end of measurement window)
  velocityquant-v3-hourly.service          loaded    inactive   dead               VelocityQuant R74 V3 Hourly Tracker (auto-fill H1-H6 + auto-rollback Gemma matrix)
● vq-adp-capture.service                   loaded    failed     failed             VelocityQuant ADP capture (one-shot at 12:14:30 UTC)
  vq-burnin-sample.service                 loaded    inactive   dead               VelocityQuant Burn-in 24h monitoring sample (r136 firma Gemma)
  vq-debatebots-upload.service             loaded    active     running            DebateBots Upload Server (Dallas standalone, separate from V4)
  vq-pnl-shadow-cache.service              loaded    activating start        start VelocityQuant PNL — refresh shadow_summary cache (full scan cyclic_shadow JSONLs)
  vq-pnl-snapshot.service                  loaded    inactive   dead               VelocityQuant PNL — wallet balance snapshot to balance_snapshots.jsonl
  vq-poly-api.service                      loaded    active     running            VelocityQuant Polymarket Sidecar — FastAPI (uvicorn) on :8090
  vq-poly-sidecar.service                  loaded    active     running            VelocityQuant Polymarket Sentiment Sidecar — main loop
  vq-shadow-rsync.service                  loaded    inactive   dead               VelocityQuant SHADOW JSONL mirror — rsync Newark→Dallas every 60s
```

## All timers
```
NEXT                             LEFT LAST                              PASSED UNIT                                  ACTIVATES
Sat 2026-05-09 07:16:05 UTC        7s Sat 2026-05-09 07:15:35 UTC      22s ago hftbots-evaluator.timer               hftbots-evaluator.service
Sat 2026-05-09 07:16:13 UTC       16s Sat 2026-05-09 07:15:13 UTC      43s ago vq-burnin-sample.timer                vq-burnin-sample.service
Sat 2026-05-09 07:16:13 UTC       16s Sat 2026-05-09 07:15:13 UTC      43s ago vq-shadow-rsync.timer                 vq-shadow-rsync.service
Sat 2026-05-09 07:17:09 UTC  1min 12s Sat 2026-05-09 07:02:09 UTC    13min ago velocityquant-refill-sol.timer        velocityquant-refill-sol.service
Sat 2026-05-09 07:17:09 UTC  1min 12s Sat 2026-05-09 07:02:09 UTC    13min ago velocityquant-refill-x402.timer       velocityquant-refill-x402.service
Sat 2026-05-09 07:20:00 UTC   4min 2s Sat 2026-05-09 07:10:00 UTC     5min ago sysstat-collect.timer                 sysstat-collect.service
Sat 2026-05-09 07:20:29 UTC  4min 32s Sat 2026-05-09 07:15:29 UTC      27s ago vq-pnl-snapshot.timer                 vq-pnl-snapshot.service
Sat 2026-05-09 07:24:42 UTC      8min Sat 2026-05-09 07:14:42 UTC 1min 15s ago hftbots-pair-scanner.timer            hftbots-pair-scanner.service
Sat 2026-05-09 07:32:45 UTC     16min Sat 2026-05-09 07:02:45 UTC    13min ago sync-newark.timer                     sync-newark.service
Sat 2026-05-09 07:37:34 UTC     21min Sat 2026-05-09 07:07:34 UTC     8min ago velocityquant-pathc-healthcheck.timer velocityquant-pathc-healthcheck.service
Sat 2026-05-09 07:49:35 UTC     33min Sat 2026-05-09 06:49:35 UTC    26min ago velocityquant-v3-hourly.timer         velocityquant-v3-hourly.service
Sat 2026-05-09 08:00:40 UTC     44min Sat 2026-05-09 07:01:37 UTC    14min ago bot3_prime_git_backup.timer           bot3_prime_git_backup.service
Sat 2026-05-09 08:01:33 UTC     45min Sat 2026-05-09 07:01:20 UTC    14min ago bot3_prime_bitunix_git_backup.timer   bot3_prime_bitunix_git_backup.service
Sat 2026-05-09 08:29:28 UTC  1h 13min Sat 2026-05-09 07:15:42 UTC      15s ago fwupd-refresh.timer                   fwupd-refresh.service
Sat 2026-05-09 10:12:51 UTC  2h 56min Fri 2026-05-08 19:05:35 UTC      12h ago motd-news.timer                       motd-news.service
Sat 2026-05-09 13:37:49 UTC        6h Fri 2026-05-08 13:37:49 UTC      17h ago diskinfocheck.timer                   diskinfocheck.service
Sat 2026-05-09 13:42:13 UTC        6h Fri 2026-05-08 13:42:13 UTC      17h ago update-notifier-download.timer        update-notifier-download.service
Sat 2026-05-09 13:51:06 UTC        6h Fri 2026-05-08 13:51:06 UTC      17h ago systemd-tmpfiles-clean.timer          systemd-tmpfiles-clean.service
Sat 2026-05-09 14:00:15 UTC        6h Sat 2026-05-09 04:01:07 UTC 3h 14min ago certbot.timer                         certbot.service
Sat 2026-05-09 14:41:41 UTC        7h Sat 2026-05-09 05:35:33 UTC 1h 40min ago apt-daily.timer                       apt-daily.service
Sun 2026-05-10 00:00:00 UTC       16h Sat 2026-05-09 00:00:00 UTC       7h ago dpkg-db-backup.timer                  dpkg-db-backup.service
Sun 2026-05-10 00:00:00 UTC       16h Sat 2026-05-09 00:00:00 UTC       7h ago logrotate.timer                       logrotate.service
Sun 2026-05-10 00:07:00 UTC       16h Sat 2026-05-09 00:07:00 UTC       7h ago sysstat-summary.timer                 sysstat-summary.service
Sun 2026-05-10 02:37:27 UTC       19h Sat 2026-05-09 05:35:33 UTC 1h 40min ago man-db.timer                          man-db.service
Sun 2026-05-10 03:10:05 UTC       19h Sun 2026-05-03 03:10:12 UTC   6 days ago e2scrub_all.timer                     e2scrub_all.service
Sun 2026-05-10 03:30:00 UTC       20h -                                      - poly_log_rotator.timer                poly_log_rotator.service
Sun 2026-05-10 06:41:43 UTC       23h Sat 2026-05-09 06:40:55 UTC    35min ago apt-daily-upgrade.timer               apt-daily-upgrade.service
Mon 2026-05-11 00:31:07 UTC 1 day 17h Mon 2026-05-04 00:47:46 UTC   5 days ago fstrim.timer                          fstrim.service
Sat 2026-05-16 03:04:45 UTC    6 days Wed 2026-05-06 08:26:14 UTC   2 days ago update-notifier-motd.timer            update-notifier-motd.service
-                                   - -                                      - apport-autoreport.timer               apport-autoreport.service
-                                   - Wed 2026-05-06 07:20:37 UTC   2 days ago cafecito.timer                        cafecito.service
-                                   - -                                      - snapd.snap-repair.timer               snapd.snap-repair.service
-                                   - -                                      - ua-timer.timer                        ua-timer.service
-                                   - Sat 2026-05-09 07:15:55 UTC       2s ago velocityquant-shadow-collector.timer  velocityquant-shadow-collector.service
-                                   - Sun 2026-05-03 22:44:31 UTC   5 days ago velocityquant-v21-autoreport.timer    velocityquant-v21-autoreport.service
-                                   - Wed 2026-05-06 12:14:30 UTC   2 days ago vq-adp-capture.timer                  vq-adp-capture.service
-                                   - Sat 2026-05-09 07:15:29 UTC      27s ago vq-pnl-shadow-cache.timer             vq-pnl-shadow-cache.service

37 timers listed.
```

## Failed services details
```
  UNIT                                    LOAD   ACTIVE SUB    DESCRIPTION
● dhcp-interface@br-660ee1c41353.service  loaded failed failed DHCP interface br-660ee1c41353
● dhcp-interface@docker0.service          loaded failed failed DHCP interface docker0
● dhcp-interface@eth1.service             loaded failed failed DHCP interface eth1
● dhcp-interface@eth2.service             loaded failed failed DHCP interface eth2
● dhcp-interface@eth3.service             loaded failed failed DHCP interface eth3
● dhcp-interface@veth0738f31.service      loaded failed failed DHCP interface veth0738f31
● dhcp-interface@veth4c7f839.service      loaded failed failed DHCP interface veth4c7f839
● dhcp-interface@veth5aaeaea.service      loaded failed failed DHCP interface veth5aaeaea
● dhcp-interface@veth717eafc.service      loaded failed failed DHCP interface veth717eafc
● dhcp-interface@veth836112a.service      loaded failed failed DHCP interface veth836112a
● dhcp-interface@vethcbfaef2.service      loaded failed failed DHCP interface vethcbfaef2
● fail2ban.service                        loaded failed failed Fail2Ban Service
● trading_bot.service                     loaded failed failed Trading Bot Service
● velocityquant-pathc-healthcheck.service loaded failed failed VelocityQuant Path C Health Check (R74 V2.1)
● vq-adp-capture.service                  loaded failed failed VelocityQuant ADP capture (one-shot at 12:14:30 UTC)

Legend: LOAD   → Reflects whether the unit definition was properly loaded.
        ACTIVE → The high-level unit activation state, i.e. generalization of SUB.
        SUB    → The low-level unit activation state, values depend on unit type.

15 loaded units listed.
```
