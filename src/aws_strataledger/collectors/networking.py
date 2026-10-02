from __future__ import annotations

"""
Networking & Connectivity collectors.

Covers: VPC (Subnets, SGs, NACLs, Route Tables, IGWs, NAT GWs, EIPs, Endpoints),
        Transit Gateway, VPC Peering, Site-to-Site VPN, Direct Connect,
        ELB, API Gateway, Route 53, Network Firewall, WAF, Shield
"""

from .base import BaseCollector


class NetworkingCollector(BaseCollector):
    """Collects all networking and connectivity resources."""

    SERVICE_NAME = "networking"

    def collect(self) -> dict:
        results = {}

        # VPC resources
        results["vpcs"] = self._collect_vpcs()
        results["subnets"] = self._collect_subnets()
        results["security_groups"] = self._collect_security_groups()
        results["network_acls"] = self._collect_nacls()
        results["route_tables"] = self._collect_route_tables()
        results["internet_gateways"] = self._collect_igws()
        results["nat_gateways"] = self._collect_nat_gateways()
        results["elastic_ips"] = self._collect_eips()
        results["vpc_endpoints"] = self._collect_vpc_endpoints()

        # Transit Gateway
        results["transit_gateways"] = self._collect_transit_gateways()
        results["transit_gateway_attachments"] = self._collect_tgw_attachments()
        results["transit_gateway_route_tables"] = self._collect_tgw_route_tables()
        results["transit_gateway_peerings"] = self._collect_tgw_peerings()

        # Peering & VPN
        results["vpc_peering_connections"] = self._collect_vpc_peering()
        results["vpn_connections"] = self._collect_vpn_connections()
        results["vpn_gateways"] = self._collect_vpn_gateways()
        results["customer_gateways"] = self._collect_customer_gateways()

        # Direct Connect
        results["direct_connect_connections"] = self._collect_dx_connections()

        # Load Balancing
        results["load_balancers_v2"] = self._collect_elbv2()
        results["load_balancers_classic"] = self._collect_elb_classic()
        results["target_groups"] = self._collect_target_groups()

        # API Gateway
        results["api_gateway_rest_apis"] = self._collect_apigw_rest()
        results["api_gateway_http_apis"] = self._collect_apigw_http()

        # Network Firewall
        results["network_firewalls"] = self._collect_network_firewalls()

        # WAF (Regional scope)
        results["waf_web_acls"] = self._collect_waf_regional()

        return results

    # ── VPC ──────────────────────────────────────────────────────────

    def _collect_vpcs(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        vpcs = self._safe_paginate(ec2, "describe_vpcs", "Vpcs")
        return [
            {
                "resource_type": "vpc",
                "resource_id": v["VpcId"],
                "name": self._get_name_tag(v),
                "cidr_block": v.get("CidrBlock"),
                "cidr_block_associations": [
                    a.get("CidrBlock") for a in v.get("CidrBlockAssociationSet", [])
                ],
                "is_default": v.get("IsDefault", False),
                "state": v.get("State"),
                "dhcp_options_id": v.get("DhcpOptionsId"),
                "tags": self._extract_tags(v),
                "region": self.region,
                "account_id": self.account_id,
            }
            for v in vpcs
        ]

    def _collect_subnets(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        subnets = self._safe_paginate(ec2, "describe_subnets", "Subnets")
        return [
            {
                "resource_type": "subnet",
                "resource_id": s["SubnetId"],
                "name": self._get_name_tag(s),
                "vpc_id": s.get("VpcId"),
                "cidr_block": s.get("CidrBlock"),
                "availability_zone": s.get("AvailabilityZone"),
                "availability_zone_id": s.get("AvailabilityZoneId"),
                "available_ip_count": s.get("AvailableIpAddressCount"),
                "map_public_ip_on_launch": s.get("MapPublicIpOnLaunch", False),
                "default_for_az": s.get("DefaultForAz", False),
                "state": s.get("State"),
                "tags": self._extract_tags(s),
                "region": self.region,
                "account_id": self.account_id,
            }
            for s in subnets
        ]

    def _collect_security_groups(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        sgs = self._safe_paginate(ec2, "describe_security_groups", "SecurityGroups")
        return [
            {
                "resource_type": "security_group",
                "resource_id": sg["GroupId"],
                "name": sg.get("GroupName", ""),
                "description": sg.get("Description", ""),
                "vpc_id": sg.get("VpcId"),
                "ingress_rules": self._format_sg_rules(sg.get("IpPermissions", [])),
                "egress_rules": self._format_sg_rules(sg.get("IpPermissionsEgress", [])),
                "ingress_rule_count": len(sg.get("IpPermissions", [])),
                "egress_rule_count": len(sg.get("IpPermissionsEgress", [])),
                "tags": self._extract_tags(sg),
                "region": self.region,
                "account_id": self.account_id,
            }
            for sg in sgs
        ]

    def _format_sg_rules(self, rules: list) -> list[dict]:
        formatted = []
        for rule in rules:
            formatted.append({
                "protocol": rule.get("IpProtocol", ""),
                "from_port": rule.get("FromPort"),
                "to_port": rule.get("ToPort"),
                "cidr_ranges": [r.get("CidrIp", "") for r in rule.get("IpRanges", [])],
                "ipv6_ranges": [r.get("CidrIpv6", "") for r in rule.get("Ipv6Ranges", [])],
                "referenced_sgs": [
                    r.get("GroupId", "") for r in rule.get("UserIdGroupPairs", [])
                ],
                "prefix_lists": [
                    r.get("PrefixListId", "") for r in rule.get("PrefixListIds", [])
                ],
            })
        return formatted

    def _collect_nacls(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        nacls = self._safe_paginate(ec2, "describe_network_acls", "NetworkAcls")
        return [
            {
                "resource_type": "network_acl",
                "resource_id": n["NetworkAclId"],
                "name": self._get_name_tag(n),
                "vpc_id": n.get("VpcId"),
                "is_default": n.get("IsDefault", False),
                "entries": [
                    {
                        "rule_number": e.get("RuleNumber"),
                        "protocol": e.get("Protocol"),
                        "rule_action": e.get("RuleAction"),
                        "egress": e.get("Egress"),
                        "cidr_block": e.get("CidrBlock"),
                    }
                    for e in n.get("Entries", [])
                ],
                "associations": [
                    a.get("SubnetId") for a in n.get("Associations", [])
                ],
                "tags": self._extract_tags(n),
                "region": self.region,
                "account_id": self.account_id,
            }
            for n in nacls
        ]

    def _collect_route_tables(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        rts = self._safe_paginate(ec2, "describe_route_tables", "RouteTables")
        return [
            {
                "resource_type": "route_table",
                "resource_id": rt["RouteTableId"],
                "name": self._get_name_tag(rt),
                "vpc_id": rt.get("VpcId"),
                "routes": [
                    {
                        "destination": r.get("DestinationCidrBlock") or r.get("DestinationIpv6CidrBlock") or r.get("DestinationPrefixListId", ""),
                        "target": (
                            r.get("GatewayId") or r.get("NatGatewayId") or
                            r.get("TransitGatewayId") or r.get("VpcPeeringConnectionId") or
                            r.get("VpcEndpointId") or r.get("NetworkInterfaceId") or
                            r.get("InstanceId") or r.get("CarrierGatewayId") or
                            r.get("LocalGatewayId") or r.get("CoreNetworkArn") or "local"
                        ),
                        "state": r.get("State"),
                    }
                    for r in rt.get("Routes", [])
                ],
                "associations": [
                    {
                        "subnet_id": a.get("SubnetId"),
                        "main": a.get("Main", False),
                    }
                    for a in rt.get("Associations", [])
                ],
                "tags": self._extract_tags(rt),
                "region": self.region,
                "account_id": self.account_id,
            }
            for rt in rts
        ]

    def _collect_igws(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        igws = self._safe_paginate(ec2, "describe_internet_gateways", "InternetGateways")
        return [
            {
                "resource_type": "internet_gateway",
                "resource_id": igw["InternetGatewayId"],
                "name": self._get_name_tag(igw),
                "attachments": [
                    {"vpc_id": a.get("VpcId"), "state": a.get("State")}
                    for a in igw.get("Attachments", [])
                ],
                "tags": self._extract_tags(igw),
                "region": self.region,
                "account_id": self.account_id,
            }
            for igw in igws
        ]

    def _collect_nat_gateways(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        nats = self._safe_paginate(ec2, "describe_nat_gateways", "NatGateways")
        return [
            {
                "resource_type": "nat_gateway",
                "resource_id": n["NatGatewayId"],
                "name": self._get_name_tag(n),
                "vpc_id": n.get("VpcId"),
                "subnet_id": n.get("SubnetId"),
                "state": n.get("State"),
                "connectivity_type": n.get("ConnectivityType"),
                "public_ip": next(
                    (a.get("PublicIp") for a in n.get("NatGatewayAddresses", [])
                     if a.get("PublicIp")), None
                ),
                "private_ip": next(
                    (a.get("PrivateIp") for a in n.get("NatGatewayAddresses", [])
                     if a.get("PrivateIp")), None
                ),
                "tags": self._extract_tags(n),
                "region": self.region,
                "account_id": self.account_id,
            }
            for n in nats
            if n.get("State") != "deleted"
        ]

    def _collect_eips(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        addresses = self._safe_call(
            lambda: ec2.describe_addresses().get("Addresses", []),
            default=[],
        )
        return [
            {
                "resource_type": "elastic_ip",
                "resource_id": a.get("AllocationId", a.get("PublicIp")),
                "name": self._get_name_tag(a),
                "public_ip": a.get("PublicIp"),
                "association_id": a.get("AssociationId"),
                "instance_id": a.get("InstanceId"),
                "network_interface_id": a.get("NetworkInterfaceId"),
                "domain": a.get("Domain"),
                "tags": self._extract_tags(a),
                "region": self.region,
                "account_id": self.account_id,
            }
            for a in addresses
        ]

    def _collect_vpc_endpoints(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        endpoints = self._safe_paginate(ec2, "describe_vpc_endpoints", "VpcEndpoints")
        return [
            {
                "resource_type": "vpc_endpoint",
                "resource_id": ep["VpcEndpointId"],
                "name": self._get_name_tag(ep),
                "vpc_id": ep.get("VpcId"),
                "service_name": ep.get("ServiceName", ""),
                "endpoint_type": ep.get("VpcEndpointType"),
                "state": ep.get("State"),
                "subnet_ids": ep.get("SubnetIds", []),
                "network_interface_ids": ep.get("NetworkInterfaceIds", []),
                "route_table_ids": ep.get("RouteTableIds", []),
                "security_group_ids": [g.get("GroupId") for g in ep.get("Groups", [])],
                "tags": self._extract_tags(ep),
                "region": self.region,
                "account_id": self.account_id,
            }
            for ep in endpoints
        ]

    # ── Transit Gateway ──────────────────────────────────────────────

    def _collect_transit_gateways(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        tgws = self._safe_paginate(ec2, "describe_transit_gateways", "TransitGateways")
        return [
            {
                "resource_type": "transit_gateway",
                "resource_id": t["TransitGatewayId"],
                "name": self._get_name_tag(t),
                "state": t.get("State"),
                "owner_id": t.get("OwnerId"),
                "amazon_side_asn": t.get("Options", {}).get("AmazonSideAsn"),
                "auto_accept_shared": t.get("Options", {}).get(
                    "AutoAcceptSharedAttachments"
                ),
                "default_route_table_association": t.get("Options", {}).get(
                    "DefaultRouteTableAssociation"
                ),
                "tags": self._extract_tags(t),
                "region": self.region,
                "account_id": self.account_id,
            }
            for t in tgws
        ]

    def _collect_tgw_attachments(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        attachments = self._safe_paginate(
            ec2, "describe_transit_gateway_attachments", "TransitGatewayAttachments"
        )
        return [
            {
                "resource_type": "transit_gateway_attachment",
                "resource_id": a["TransitGatewayAttachmentId"],
                "name": self._get_name_tag(a),
                "transit_gateway_id": a.get("TransitGatewayId"),
                "resource_type_attached": a.get("ResourceType"),
                "resource_id_attached": a.get("ResourceId"),
                "resource_owner_id": a.get("ResourceOwnerId"),
                "state": a.get("State"),
                "tags": self._extract_tags(a),
                "region": self.region,
                "account_id": self.account_id,
            }
            for a in attachments
        ]

    def _collect_tgw_route_tables(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        rts = self._safe_paginate(
            ec2, "describe_transit_gateway_route_tables", "TransitGatewayRouteTables"
        )
        return [
            {
                "resource_type": "transit_gateway_route_table",
                "resource_id": rt["TransitGatewayRouteTableId"],
                "name": self._get_name_tag(rt),
                "transit_gateway_id": rt.get("TransitGatewayId"),
                "state": rt.get("State"),
                "default_association": rt.get("DefaultAssociationRouteTable", False),
                "default_propagation": rt.get("DefaultPropagationRouteTable", False),
                "tags": self._extract_tags(rt),
                "region": self.region,
                "account_id": self.account_id,
            }
            for rt in rts
        ]

    def _collect_tgw_peerings(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        peerings = self._safe_paginate(
            ec2, "describe_transit_gateway_peering_attachments", "TransitGatewayPeeringAttachments"
        )
        results = []
        for p in peerings:
            if p.get("State") in ("deleted", "deleting", "failed", "rejected"):
                continue
            req = p.get("RequesterTgwInfo") or {}
            acc = p.get("AccepterTgwInfo") or {}
            results.append({
                "resource_type": "transit_gateway_peering",
                "resource_id": p["TransitGatewayAttachmentId"],
                "name": self._get_name_tag(p),
                "state": p.get("State"),
                "requester_tgw": req.get("TransitGatewayId"),
                "requester_region": req.get("Region"),
                "requester_owner": req.get("OwnerId"),
                "accepter_tgw": acc.get("TransitGatewayId"),
                "accepter_region": acc.get("Region"),
                "accepter_owner": acc.get("OwnerId"),
                "tags": self._extract_tags(p),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    # ── VPC Peering ──────────────────────────────────────────────────

    def _collect_vpc_peering(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        pcxs = self._safe_paginate(
            ec2, "describe_vpc_peering_connections", "VpcPeeringConnections"
        )
        return [
            {
                "resource_type": "vpc_peering_connection",
                "resource_id": p["VpcPeeringConnectionId"],
                "name": self._get_name_tag(p),
                "status": p.get("Status", {}).get("Code"),
                "requester_vpc": p.get("RequesterVpcInfo", {}).get("VpcId"),
                "requester_cidr": p.get("RequesterVpcInfo", {}).get("CidrBlock"),
                "requester_owner": p.get("RequesterVpcInfo", {}).get("OwnerId"),
                "requester_region": p.get("RequesterVpcInfo", {}).get("Region"),
                "accepter_vpc": p.get("AccepterVpcInfo", {}).get("VpcId"),
                "accepter_cidr": p.get("AccepterVpcInfo", {}).get("CidrBlock"),
                "accepter_owner": p.get("AccepterVpcInfo", {}).get("OwnerId"),
                "accepter_region": p.get("AccepterVpcInfo", {}).get("Region"),
                "tags": self._extract_tags(p),
                "region": self.region,
                "account_id": self.account_id,
            }
            for p in pcxs
        ]

    # ── VPN ──────────────────────────────────────────────────────────

    def _collect_vpn_connections(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        vpns = self._safe_call(
            lambda: ec2.describe_vpn_connections().get("VpnConnections", []),
            default=[],
        )
        return [
            {
                "resource_type": "vpn_connection",
                "resource_id": v["VpnConnectionId"],
                "name": self._get_name_tag(v),
                "state": v.get("State"),
                "type": v.get("Type"),
                "vpn_gateway_id": v.get("VpnGatewayId"),
                "customer_gateway_id": v.get("CustomerGatewayId"),
                "transit_gateway_id": v.get("TransitGatewayId"),
                "tunnels": [
                    {
                        "outside_ip": t.get("OutsideIpAddress"),
                        "status": t.get("Status"),
                    }
                    for t in v.get("VgwTelemetry", [])
                ],
                "tags": self._extract_tags(v),
                "region": self.region,
                "account_id": self.account_id,
            }
            for v in vpns
            if v.get("State") != "deleted"
        ]

    def _collect_vpn_gateways(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        vgws = self._safe_call(
            lambda: ec2.describe_vpn_gateways().get("VpnGateways", []),
            default=[],
        )
        return [
            {
                "resource_type": "vpn_gateway",
                "resource_id": v["VpnGatewayId"],
                "name": self._get_name_tag(v),
                "state": v.get("State"),
                "type": v.get("Type"),
                "amazon_side_asn": v.get("AmazonSideAsn"),
                "vpc_attachments": [
                    {"vpc_id": a.get("VpcId"), "state": a.get("State")}
                    for a in v.get("VpcAttachments", [])
                ],
                "tags": self._extract_tags(v),
                "region": self.region,
                "account_id": self.account_id,
            }
            for v in vgws
            if v.get("State") != "deleted"
        ]

    def _collect_customer_gateways(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        cgws = self._safe_call(
            lambda: ec2.describe_customer_gateways().get("CustomerGateways", []),
            default=[],
        )
        return [
            {
                "resource_type": "customer_gateway",
                "resource_id": c["CustomerGatewayId"],
                "name": self._get_name_tag(c),
                "state": c.get("State"),
                "type": c.get("Type"),
                "bgp_asn": c.get("BgpAsn"),
                "ip_address": c.get("IpAddress"),
                "tags": self._extract_tags(c),
                "region": self.region,
                "account_id": self.account_id,
            }
            for c in cgws
            if c.get("State") != "deleted"
        ]

    # ── Direct Connect ───────────────────────────────────────────────

    def _collect_dx_connections(self) -> list[dict]:
        dx = self._get_client("directconnect")
        connections = self._safe_call(
            lambda: dx.describe_connections().get("connections", []),
            default=[],
        )
        return [
            {
                "resource_type": "direct_connect_connection",
                "resource_id": c["connectionId"],
                "name": c.get("connectionName", ""),
                "state": c.get("connectionState"),
                "bandwidth": c.get("bandwidth"),
                "location": c.get("location"),
                "vlan": c.get("vlan"),
                "partner_name": c.get("partnerName"),
                "region": self.region,
                "account_id": self.account_id,
            }
            for c in connections
        ]

    # ── Elastic Load Balancing ───────────────────────────────────────

    def _collect_elbv2(self) -> list[dict]:
        elbv2 = self._get_client("elbv2")
        lbs = self._safe_paginate(elbv2, "describe_load_balancers", "LoadBalancers")

        def describe(lb: dict) -> dict:
            arn = lb["LoadBalancerArn"]
            listeners = self._safe_paginate(elbv2, "describe_listeners", "Listeners", LoadBalancerArn=arn)
            return {
                "resource_type": "load_balancer_v2",
                "resource_id": arn,
                "name": lb.get("LoadBalancerName", ""),
                "dns_name": (lb.get("DNSName", "") or "").lower(),
                "type": lb.get("Type"),
                "scheme": lb.get("Scheme"),
                "state": lb.get("State", {}).get("Code"),
                "vpc_id": lb.get("VpcId"),
                "availability_zones": [
                    {"zone": az.get("ZoneName"), "subnet_id": az.get("SubnetId")}
                    for az in lb.get("AvailabilityZones", [])
                ],
                "subnet_ids": [az.get("SubnetId") for az in lb.get("AvailabilityZones", []) if az.get("SubnetId")],
                "security_groups": lb.get("SecurityGroups", []),
                "ip_address_type": lb.get("IpAddressType"),
                "listeners": [
                    {"port": l.get("Port"), "protocol": l.get("Protocol")}
                    for l in listeners
                ],
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, lbs)

    def _collect_elb_classic(self) -> list[dict]:
        elb = self._get_client("elb")
        lbs = self._safe_paginate(elb, "describe_load_balancers", "LoadBalancerDescriptions")
        return [
            {
                "resource_type": "load_balancer_classic",
                "resource_id": lb["LoadBalancerName"],
                "name": lb["LoadBalancerName"],
                "dns_name": (lb.get("DNSName", "") or "").lower(),
                "scheme": lb.get("Scheme"),
                "vpc_id": lb.get("VPCId"),
                "availability_zones": lb.get("AvailabilityZones", []),
                "subnet_ids": lb.get("Subnets", []),
                "security_groups": lb.get("SecurityGroups", []),
                "instances": [i["InstanceId"] for i in lb.get("Instances", [])],
                "listeners": [
                    {
                        "lb_port": l.get("Listener", {}).get("LoadBalancerPort"),
                        "lb_protocol": l.get("Listener", {}).get("Protocol"),
                        "instance_port": l.get("Listener", {}).get("InstancePort"),
                    }
                    for l in lb.get("ListenerDescriptions", [])
                ],
                "region": self.region,
                "account_id": self.account_id,
            }
            for lb in lbs
        ]

    def _collect_target_groups(self) -> list[dict]:
        elbv2 = self._get_client("elbv2")
        tgs = self._safe_paginate(elbv2, "describe_target_groups", "TargetGroups")

        def describe(tg: dict) -> dict:
            arn = tg["TargetGroupArn"]
            health = self._safe_call(
                lambda: elbv2.describe_target_health(TargetGroupArn=arn).get("TargetHealthDescriptions", []),
                default=[],
            ) or []
            return {
                "resource_type": "target_group",
                "resource_id": arn,
                "name": tg.get("TargetGroupName", ""),
                "protocol": tg.get("Protocol"),
                "port": tg.get("Port"),
                "target_type": tg.get("TargetType"),
                "vpc_id": tg.get("VpcId"),
                "health_check_path": tg.get("HealthCheckPath"),
                "load_balancer_arns": tg.get("LoadBalancerArns", []),
                "targets": [
                    {
                        "id": t.get("Target", {}).get("Id"),
                        "port": t.get("Target", {}).get("Port"),
                        "state": t.get("TargetHealth", {}).get("State"),
                    }
                    for t in health
                ],
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, tgs)

    # ── API Gateway ──────────────────────────────────────────────────

    def _collect_apigw_rest(self) -> list[dict]:
        apigw = self._get_client("apigateway")
        apis = self._safe_paginate(apigw, "get_rest_apis", "items")
        return [
            {
                "resource_type": "api_gateway_rest",
                "resource_id": api["id"],
                "name": api.get("name", ""),
                "description": api.get("description", ""),
                "endpoint_configuration": api.get("endpointConfiguration", {}),
                "endpoint_types": (api.get("endpointConfiguration") or {}).get("types", []),
                "created_date": str(api.get("createdDate", "")),
                "tags": api.get("tags", {}),
                "region": self.region,
                "account_id": self.account_id,
            }
            for api in apis
        ]

    def _collect_apigw_http(self) -> list[dict]:
        apigwv2 = self._get_client("apigatewayv2")
        apis = self._safe_paginate_tokens(apigwv2, "get_apis", "Items", token_in="NextToken")
        return [
            {
                "resource_type": "api_gateway_http",
                "resource_id": api["ApiId"],
                "name": api.get("Name", ""),
                "protocol_type": api.get("ProtocolType"),
                "api_endpoint": (api.get("ApiEndpoint", "") or "").lower(),
                "created_date": str(api.get("CreatedDate", "")),
                "tags": api.get("Tags", {}),
                "region": self.region,
                "account_id": self.account_id,
            }
            for api in apis
        ]

    # ── Network Firewall ─────────────────────────────────────────────

    def _collect_network_firewalls(self) -> list[dict]:
        nfw = self._get_client("network-firewall")
        firewalls = self._safe_paginate(nfw, "list_firewalls", "Firewalls")

        def describe(fw_summary: dict) -> dict | None:
            fw_name = fw_summary.get("FirewallName", "")
            fw_arn = fw_summary.get("FirewallArn", "")
            if not fw_name and not fw_arn:
                return None

            fw_detail = {}
            if fw_arn:
                fw_detail = self._safe_call(nfw.describe_firewall, default={}, FirewallArn=fw_arn)
            if not fw_detail and fw_name:
                fw_detail = self._safe_call(nfw.describe_firewall, default={}, FirewallName=fw_name)

            fw = (fw_detail or {}).get("Firewall", {})
            fw_status = (fw_detail or {}).get("FirewallStatus", {})

            raw_status = fw_status.get("Status")
            status = raw_status or ("READY" if fw_detail else "ACTIVE")

            endpoint_ids = []
            subnet_to_endpoint = {}
            for az, sync in (fw_status.get("SyncStates") or {}).items():
                if isinstance(sync, dict):
                    att = sync.get("Attachment", {})
                    ep_id = att.get("EndpointId")
                    if ep_id:
                        endpoint_ids.append(ep_id)
                        if att.get("SubnetId"):
                            subnet_to_endpoint[att["SubnetId"]] = ep_id

            return {
                "resource_type": "network_firewall",
                "resource_id": fw.get("FirewallArn") or fw_arn,
                "name": fw.get("FirewallName") or fw_name,
                "status": status,
                "vpc_id": fw.get("VpcId"),
                "transit_gateway_id": fw.get("TransitGatewayId"),
                "subnet_mappings": [
                    s.get("SubnetId") for s in fw.get("SubnetMappings", []) if s.get("SubnetId")
                ],
                "subnet_to_endpoint": subnet_to_endpoint,
                "firewall_policy_arn": fw.get("FirewallPolicyArn"),
                "endpoint_ids": endpoint_ids,
                "delete_protection": fw.get("DeleteProtection", False),
                "description": fw.get("Description", ""),
                "sync_state_summary": fw_status.get("ConfigurationSyncStateSummary", ""),
                "tags": self._extract_tags(fw),
                "region": self.region,
                "account_id": self.account_id,
            }

        return [f for f in self._parallel(describe, firewalls, max_workers=4) if f]

    # ── WAF (Regional scope) ─────────────────────────────────────────

    def _collect_waf_regional(self) -> list[dict]:
        wafv2 = self._get_client("wafv2")
        acls = self._safe_paginate_tokens(
            wafv2, "list_web_acls", "WebACLs", token_in="NextMarker",
            Scope="REGIONAL",
        )

        def describe(acl: dict) -> dict:
            arn = acl.get("ARN", acl.get("Id", ""))
            resources = self._safe_call(
                lambda: wafv2.list_resources_for_web_acl(WebACLArn=arn).get("ResourceArns", []),
                default=[],
            ) or []
            return {
                "resource_type": "waf_web_acl",
                "resource_id": arn,
                "name": acl.get("Name", ""),
                "status": "ACTIVE",
                "scope": "REGIONAL",
                "description": acl.get("Description", ""),
                "associated_resources": resources,
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, acls)
