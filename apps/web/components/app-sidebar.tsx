"use client";

import {
  BookOpen,
  FlaskConical,
  LayoutDashboard,
  MessageSquare,
  ShieldCheck,
  Ticket,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";

interface NavItem {
  title: string;
  href: string;
  icon: LucideIcon;
  /** Set until the feature exists, so the shell never pretends unbuilt pages work. */
  comingInPhase?: number;
}

const NAV: NavItem[] = [
  { title: "Overview", href: "/", icon: LayoutDashboard },
  { title: "Assistant", href: "/assistant", icon: MessageSquare, comingInPhase: 3 },
  { title: "Knowledge Hub", href: "/knowledge", icon: BookOpen, comingInPhase: 2 },
  { title: "Tickets & Reports", href: "/workflows", icon: Ticket, comingInPhase: 7 },
  { title: "Security Center", href: "/security", icon: ShieldCheck, comingInPhase: 8 },
  { title: "Evaluation", href: "/evaluation", icon: FlaskConical, comingInPhase: 4 },
];

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1.5">
          <div className="bg-primary text-primary-foreground flex size-7 shrink-0 items-center justify-center rounded-md text-xs font-semibold">
            OM
          </div>
          <span className="truncate font-semibold group-data-[collapsible=icon]:hidden">
            Office-Mates
          </span>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => {
                const Icon = item.icon;
                if (item.comingInPhase !== undefined) {
                  return (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton
                        disabled
                        aria-disabled
                        tooltip={`${item.title} (Phase ${item.comingInPhase})`}
                        className="opacity-60"
                      >
                        <Icon />
                        <span>{item.title}</span>
                      </SidebarMenuButton>
                      <SidebarMenuBadge>P{item.comingInPhase}</SidebarMenuBadge>
                    </SidebarMenuItem>
                  );
                }
                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      isActive={pathname === item.href}
                      tooltip={item.title}
                      render={<Link href={item.href} />}
                    >
                      <Icon />
                      <span>{item.title}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <p className="text-muted-foreground px-2 text-xs group-data-[collapsible=icon]:hidden">
          Phase 0 · foundations
        </p>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
