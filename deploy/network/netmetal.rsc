# RouterOS 7 WiFi: NetMetal rover station. REVIEW TEMPLATE ONLY.
# Run only with wired recovery access and approved exported-config backup.
# Inspect/disable conflicting Netwatch/schedulers by exact ID FIRST; see RUNBOOK.
:local reviewed false
:if (!$reviewed) do={ :error "Review topology, interfaces, firewall and rollback before importing" }
:local if5 "REPLACE_WIFI_5"
:local if24 "REPLACE_WIFI_24"
:local lan "REPLACE_LAN_BRIDGE"
:if ($if5 = $if24) do={ :error "Bands require distinct interfaces" }
:if ([:len [/interface find where name=$if5]] != 1) do={ :error "5 GHz interface missing" }
:if ([:len [/interface find where name=$if24]] != 1) do={ :error "2.4 GHz interface missing" }
:if ([:len [/interface bridge find where name=$lan]] != 1) do={ :error "LAN bridge missing" }
# Existing WiFi security/SSID/channel settings are preserved. Both radios must stay enabled.
# The two WiFi interfaces MUST leave the shared RSTP bridge for independent routed paths.
/interface bridge port remove [find where interface=$if5]
/interface bridge port remove [find where interface=$if24]
/ip address add address=10.42.0.1/24 interface=$lan comment="irc-rover-lan"
/ip address add address=10.44.50.2/30 interface=$if5 comment="irc-rover-transit-5"
/routing table add name=irc-probe-5 fib
/ip route add dst-address=10.44.50.1/32 gateway=$if5 routing-table=irc-probe-5 comment="irc-rover-probe-5"
/routing rule add dst-address=10.44.50.1/32 action=lookup-only-in-table table=irc-probe-5 comment="irc-rover-pin-5"
# Fail closed: lookup-only table has no alternate/default route.
/ip route add disabled=yes dst-address=10.43.0.0/24 gateway=("10.44.50.1%" . $if5) distance=1 comment="irc-rover-via-5"
/ip address add address=10.44.24.2/30 interface=$if24 comment="irc-rover-transit-24"
/routing table add name=irc-probe-24 fib
/ip route add dst-address=10.44.24.1/32 gateway=$if24 routing-table=irc-probe-24 comment="irc-rover-probe-24"
/routing rule add dst-address=10.44.24.1/32 action=lookup-only-in-table table=irc-probe-24 comment="irc-rover-pin-24"
# Fail closed: lookup-only table has no alternate/default route.
/ip route add disabled=yes dst-address=10.43.0.0/24 gateway=("10.44.24.1%" . $if24) distance=20 comment="irc-rover-via-24"
# SERVICE ROUTES ARE DISABLED. Enable exact two irc-*-via-* IDs for supervised static-path tests.
# No radio disable, channel hopping, NAT, DHCP, Internet or existing firewall changes are performed here.
# Firewall requirements and rule ordering are in RUNBOOK; adapt to the actual export.
# Pin return probes using the same peer-specific lookup-only rules at the OTHER CPE.
