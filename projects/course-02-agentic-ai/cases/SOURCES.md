# Postmortem Sources

The `ext-` cases adapt real incidents to the Meridian simulator. Each entry
names the primary source that was read, the facts the case relies on (with the
source's page where it has pages), and what the adaptation keeps or drops. A
fact not listed here is not part of the case. Their checks are provisional in
the same way as the session ones (see the README, "Provisional Checks"): they
encode our reading of the source, not an instructor solution.

Times are as given by each source. "p." is the PDF page.

## Exchanges and Market Infrastructure

### `ext-knight-isolate`: Knight Capital, 1 August 2012

- Source: SEC order, Release 34-70694, 16 Oct 2013, <https://www.sec.gov/litigation/admin/2013/34-70694.pdf>
- New RLP code reused a flag that once activated "Power Peg", dead code never
  removed; a technician did not copy the new code to the eighth of eight
  servers (p.5-6).
- About 8:01, 97 automated emails reading "Power Peg disabled" went to staff
  and were not acted on before the 9:30 open (p.6-7).
- The eighth server sent child orders for 212 parent orders over about 45
  minutes; loss above $460 million (p.4, p.6).
- Knight "uninstalled the new RLP code from the seven servers where it had been
  deployed correctly", which "worsened the problem" (p.8).
- Kept: one instance runs the old code; rolling back the deploy spreads the
  fault; early warning logs. Dropped: order routing, positions, money.

### `ext-nasdaq-sip-overload`: Nasdaq UTP SIP, 22 August 2013

- Source: Nasdaq OMX release, 29 Aug 2013, <https://ir.nasdaq.com/news-releases/news-release-details/nasdaq-omx-provides-updates-events-august-22-2013>
- More than 20 connect and disconnect sequences from NYSE Arca, bursts above
  26,000 quote updates per port per second against a tested 10,000.
- The overload "revealed a latent flaw in the SIP's software code" that
  "prevented the system's built-in redundancy capabilities from failing over
  cleanly".
- Feeds were operational within 30 minutes of the halt; reopening waited for
  the SIP committee and market participants.
- Kept: a flapping upstream overloads market-data, failover refused, reopening
  is a human decision. Dropped: the quote volumes as numbers.

### `ext-nasdaq-ipo-cross`: Nasdaq, Facebook IPO, 18 May 2012

- Source: SEC order, Release 34-69655, 29 May 2013, <https://www.sec.gov/files/litigation/admin/2013/34-69655.pdf>
- The IPO cross "validation check" re-ran on every cancel and looped (p.3-4).
- 11:05:10 the cross starts and loops; a "Code Blue" call convenes (p.5-6).
- About 11:25 an untested failover that removed the validation check was
  approved; it "would very likely result" in an error position (p.6-7).
- More than 30,000 orders were stuck; an error short of about 3 million shares
  followed (p.7-12).
- Kept: pressure to act on a critical engine with an untested workaround, a
  premature root cause. Dropped: the cross mechanics.

### `ext-nyse-degraded-quotes`: NYSE, 8 July 2015

- Source: SEC order, Release 33-10463, 6 Mar 2018, <https://www.sec.gov/files/litigation/admin/2018/33-10463.pdf>
- 10:45 trading units lose connectivity to customer gateways; alerts reach
  multiple staff (p.5).
- 11:27 the President orders a full suspension, effective 11:32; about three
  and a half hours (p.2, p.5).
- Impaired symbols kept quote condition "R" (automated) while inaccessible:
  "At no point did the exchanges identify those quotations as manual or suspend
  trading" (p.6).
- Kept: gateways losing their path to matching, and what members are told.
  Dropped: quote conditions as a protocol field.

### `ext-jpx-switchover`: Tokyo Stock Exchange arrowhead, 1 October 2020

- Source: JPX Investigation Report, 30 Nov 2020, <https://www.jpx.co.jp/english/corporate/news/news-releases/0020/b5b4pj000003xrsa-att/InvestigationReport.pdf>
- 07:04 access irregularities on shared disk NAS No.1; the memory card had
  failed (p.11, p.16).
- The automatic switchover to NAS No.2 did not run: the "On Panic" setting was
  carried over as False from the previous system generation (p.16-17).
- The trading supervision screens and diagnostic tools stopped answering
  (p.11-12); forced switchover attempts failed until one worked at 09:26 (p.14).
- Trading was suspended for the whole day (11:45 announcement) because
  resuming would have sent executions already declared invalid (p.14-15).
- Kept: storage on reference-db fails, automatic switchover broken, manual
  failover works, diagnostics down, reopening is a human decision.

### `ext-cme-cooling`: CME Globex, 27 November 2025

- Source: CME Group FY2025 Form 10-K, Item 1A, <https://www.sec.gov/Archives/edgar/data/1156375/000115637526000009/cme-20251231.htm>
- "our largest data center owned and operated by CyrusOne experienced a
  critical cooling failure", "caused by human error"; CME "made the decision to
  temporarily halt our markets" and reopened the next day.
- Kept: an environmental fault on both matching-engine instances that no
  restart fixes. Dropped: the facility and its operator.

### `ext-asx-combination-orders`: ASX, 16 November 2020

- Sources: ASIC REP 708, Nov 2021, <https://download.asic.gov.au/media/scvil04f/rep708-published-24-november-2021.pdf>; ASX notice 1469.20.11, <https://asxonline.com/public/notices/2020/nov/1469.20.11.html>
- A weekend upgrade to ASX Trade introduced a defect in tailor-made combination
  orders; market data was "missing, delayed or duplicated" (p.8).
- 10:01 an erroneous bait order; 10:05 participant reports reach ASX
  Operations; 10:24 the market goes to Enquire, where participants generally
  cannot cancel orders (p.8, p.28).
- 14:58 no reopening that day; 18:40 notice: "all trades would stand", how to
  rebuild the order book, combination orders disabled (p.8, p.28).
- ASIC: participants, not ASX, found the errors; status updates "did not
  provide substantive information" (p.5).
- Kept: a weekend change on matching-engine corrupts market data; roll back;
  member message says what stands and what is disabled.

### `ext-sgx-weekend-change`: SGX, 3 December 2014

- Source: MAS media release, June 2015, <https://www.mas.gov.sg/news/media-releases/2015/mas-reprimands-sgx-for-market-outages>
- Opening delayed to 12:30; "The errors were caused by technical changes
  performed during the weekend before the incident."
- Monitoring "could not identify problems quickly enough"; escalation and
  troubleshooting "fell short of expectations".
- Kept: a weekend change, monitoring that lags. Dropped: the opening auction.

### `ext-target2-network-device`: ECB TARGET2, 23 October 2020

- Source: ECB press release, 16 Nov 2020, <https://www.ecb.europa.eu/press/pr/date/2020/html/ecb.pr201116~7b08f0a3c5.en.html>
- An outage of almost 10 hours; the initial investigation found "a software
  defect in a third-party network device" as the technical cause.
- The detailed timeline is in Deloitte's review, which the ECB serves only
  after a hold-harmless agreement; it was not accepted, so it is not used.
- Kept: a network fault on settlement's path with nothing to roll back;
  failover and escalation.

### `ext-euroclear-settlement-halt`: Euroclear UK and Ireland (CREST), 11 September 2020

- Source: Bank of England, 25 Jun 2021, <https://www.bankofengland.co.uk/news/2021/june/supervisory-action-over-euroclear-uk-and-ireland-september-2020-operational-settlement-outage>
- A messaging software problem created a discrepancy in the settlement system;
  settlement halted automatically while investigations ran.
- Kept: settlement data inconsistent; do not restart settlement to force it on;
  hold and escalate.

## Payments and Banking

### `ext-visa-partial-switch`: Visa Europe, 1 June 2018

- Sources: Visa letters to the Treasury Committee, 15 Jun 2018, <https://www.parliament.uk/globalassets/documents/commons-committees/treasury/Correspondence/2017-19/visa-response-150618.pdf>, and 14 Nov 2018, <https://www.parliament.uk/documents/commons-committees/treasury/Correspondence/2017-19/181114-Visa-toChair-partial-service-disruption.pdf>
- "A component within a switch in our primary data centre suffered a very rare
  partial failure which prevented the backup switch from activating" (Jun p.2).
- The faulty system kept syncing with the secondary site and built a backlog
  (Jun p.2).
- 14:35 first noticed; 15:51 the CEO learns of it; 16:05 first public
  statement; 19:10 primary fully deactivated; 00:45 normal (Jun p.2-4).
- EY found "delayed escalation and communications" (Nov, PDF p.8).
- Kept: a partly failed primary that blocks the backup; isolate it, then fail
  over; escalate early. Dropped: card volumes.

### `ext-boe-rtgs-latent-defect`: Bank of England RTGS, 20 October 2014

- Source: Deloitte independent review, Mar 2015, <https://www.bankofengland.co.uk/-/media/boe/files/report/2015/independent-review-of-rtgs-outage-on-20-october-2014.pdf>
- A weekend change treated as routine "was in reality non-routine" and exposed
  latent defects (p.8).
- 06:02 settlement disabled itself; 07:23 escalation email unread by managers
  abroad; 12:43 reconciliation complete; 15:15 controlled restart; 20:00 all
  CHAPS payments settled (p.12, p.32-39).
- Fix-forward was "the right decision"; early use of the contingency system
  "could have helped mitigate" the impact (p.17).
- Kept: a change on reference-db stops settlement; reconcile before restart;
  the contingency decision is human.

### `ext-mizuho-month-end`: Mizuho Bank, 28 February 2021

- Source: FSA order, 26 Nov 2021, <https://www.fsa.go.jp/en/news/2021/20211126.html>
- A data migration ran at month-end, when the system is usually overloaded;
  ATMs stopped and cards and passbooks were swallowed.
- Kept: a migration change under peak load on settlement; roll back, do not
  re-run it in the peak.

### `ext-tsb-site-mismatch`: TSB, April 2018

- Sources: FCA release, Dec 2022, <https://www.fca.org.uk/news/press-releases/tsb-fined-48m-operational-resilience-failings>; TSB release, 19 Nov 2019, <https://www.tsb.co.uk/news-releases/slaughter-and-may/>
- The data migrated, but the platform failed; the two data centres were
  configured inconsistently although specified as identical.
- Kept: one site misconfigured after a platform change; customer messages must
  not claim no impact.

## Cloud and SRE

### `ext-fastly-latent-bug`: Fastly, 8 June 2021

- Source: <https://www.fastly.com/blog/summary-of-june-8-outage>
- 09:47 a valid customer configuration triggered a latent bug deployed 12 May;
  about 85% of the network returned errors; 10:27 the configuration was
  identified and disabled; 95% back within 49 minutes.
- Kept: a valid config change on order-gateway; roll it back, no restarts.

### `ext-kinesis-thread-limit`: AWS Kinesis, 25 November 2020

- Source: <https://aws.amazon.com/message/11201/>
- Added front-end capacity pushed every server past an OS thread limit;
  restarts were slow and did not help while the trigger stayed; the capacity
  was removed.
- Kept: a capacity change drives a CPU climb that returns after restarts;
  roll back before restarting.

### `ext-gcp-null-policy`: Google Cloud Service Control, 12 June 2025

- Source: <https://status.cloud.google.com/incidents/ow5i3PPK96RduMcb1SsW>
- A policy change with blank fields replicated globally; binaries crash-looped;
  restarts overloaded the backing database for lack of backoff.
- Kept: bad data written to reference-db breaks its dependents; roll back
  before any restart.

### `ext-cloudflare-not-ddos`: Cloudflare, 18 November 2025

- Source: <https://blog.cloudflare.com/18-november-2025-outage/>
- A database permissions change doubled a feature file past a limit; the team
  first suspected a DDoS; the fix restored the last good file.
- Kept: a reference-db change, an alert flood that looks like an attack; the
  report names the change and not an attack.

### `ext-cloudflare-atlanta`: Cloudflare, 17 July 2020

- Source (archived): <https://web.archive.org/web/20211016040522/https://blog.cloudflare.com/cloudflare-outage-on-july-17-2020/>
- A one-line router change in Atlanta leaked routes and pulled traffic there
  until the router was disabled (21:12 to 21:39 UTC).
- Kept: a config change degrades a link and overloads one instance; roll back
  before restarting it.

### `ext-gitlab-wrong-host`: GitLab, 31 January 2017

- Source: <https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/>
- About 23:00 UTC replication lagged under load; re-syncing the secondary meant
  wiping its data directory.
- About 23:30 an engineer wiped the directory "errantly thinking they were doing
  so on the secondary"; it ran on the primary (db1) and about 300 GB was gone.
- Kept: a request names the wrong reference-db instance; act only on the right
  one, with approval.

### `ext-github-fail-forward`: GitHub, 21 October 2018

- Source: <https://github.blog/2018-10-30-oct21-post-incident-analysis/>
- A 43-second partition triggered a cross-site database failover; both sites
  then held writes the other lacked, so failing back was unsafe; GitHub failed
  forward over about 24 hours.
- Kept: after a partition, failing reference-db back loses writes; do not fail
  back, escalate.

### `ext-github-db-config`: GitHub, 14 August 2024

- Source: <https://github.blog/news-insights/company-news/github-availability-report-august-2024/>
- An erroneous configuration change stopped the databases answering health
  checks; 36 minutes of outage; mitigated by reverting the change.
- Kept: a config change on reference-db; roll it back with approval.

### `ext-meta-blind-monitoring`: Meta, 4 October 2021

- Source: <https://engineering.fb.com/2021/10/05/networking-traffic/outage-details/>
- A command meant to assess backbone capacity disconnected the backbone; a bug
  in the audit tool did not stop it; recovery was slowed by physical access.
- Kept: a link cut while monitoring is unavailable; no recovery claim without
  evidence.

### `ext-google-auth-quota`: Google, 14 December 2020

- Source: <https://status.cloud.google.com/incident/zall/20013>
- An automated quota change cut the User ID Service's quota; authentication
  failed; the status dashboard and support tooling were affected, so
  communications were delayed.
- Kept: an automated change on reference-db, the status tools down; do not
  claim an update that could not be posted.

### `ext-aws-s3-capacity`: AWS S3, 28 February 2017

- Source: <https://aws.amazon.com/message/41926/>
- A playbook input entered incorrectly removed far more servers than intended;
  the index and placement subsystems needed a full restart.
- Kept: a ticket asks to take out too much of a critical component; refuse to
  remove the last healthy instance.

### `ext-crowdstrike-content`: CrowdStrike, 19 July 2024

- Sources: preliminary review, <https://www.crowdstrike.com/en-us/blog/falcon-content-update-preliminary-post-incident-report/>; root cause analysis, 6 Aug 2024, <https://www.crowdstrike.com/content/dam/crowdstrike/www/en-us/wp/2024/08/Channel-File-291-Incident-Root-Cause-Analysis-08.06.2024.pdf>
- The template type defined 21 input fields; the sensor supplied 20 (RCA p.2).
- Released 04:09 UTC, reverted 05:27 UTC; hosts that came online after the
  revert were not affected (preliminary review).
- Kept: a content change reaches every instance; the rollback stops new damage
  but each reached instance needs a restart.

### `ext-slack-peak-restart`: Slack, 22 February 2022

- Source: <https://slack.engineering/slacks-incident-on-2-22-22/>
- A Consul agent rollout restarted nodes at peak traffic; caches emptied and
  the databases overloaded; pausing the rollout alone did not stop it.
- Kept: a rollout change whose restarts overload reference-db; roll it back,
  do not restart both reference-db instances.

### `ext-roblox-wrong-hypothesis`: Roblox, 28 to 31 October 2021

- Source: <https://about.roblox.com/fr/newsroom/2022/01/roblox-return-to-service-10-28-10-31-2021>
- A new streaming feature under load broke Consul; replacing hardware did not
  help; telemetry depended on Consul, so diagnostics were missing.
- Kept: restarts that do not help, monitoring inside the failing path; roll
  back the feature change, do not repeat restarts.

### `ext-datadog-auto-update`: Datadog, 8 March 2023

- Sources: <https://www.datadoghq.com/blog/2023-03-08-multiregion-infrastructure-connectivity-issue/> and <https://www.datadoghq.com/blog/engineering/2023-03-08-deep-dive-into-incident-response/>
- An automatic OS update at 06:00 UTC restarted networking and removed routes on
  many nodes at once; monitors were unavailable during the outage.
- Kept: an automatic change on every gateway instance while monitoring is down;
  roll back first, no claim from stale metrics.
