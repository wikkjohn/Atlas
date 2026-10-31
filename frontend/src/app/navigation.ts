import {
  ArrowLeftRight,
  Banknote,
  CandlestickChart,
  CreditCard,
  Bot,
  Building2,
  FlaskConical,
  Gauge,
  HandCoins,
  Globe2,
  LayoutDashboard,
  type LucideIcon,
  PiggyBank,
  PlayCircle,
  ScrollText,
  Settings,
  UserRound,
  Users,
  Workflow,
} from "lucide-react";

import type { Permission } from "@/types/enterprise";

export interface NavItem {
  label: string;
  path: string;
  icon: LucideIcon;
  /** Implementation phase that delivers this screen. */
  phase: number;
  /** Hidden from roles without this permission (the backend enforces it regardless). */
  permission?: Permission;
}

/** Screens up to this phase are live; later ones are shown disabled with their phase. */
export const IMPLEMENTED_PHASE = 31;

export const NAV_ITEMS: NavItem[] = [
  { label: "Overview", path: "/", icon: LayoutDashboard, phase: 1 },
  {
    label: "Organization",
    path: "/organization",
    icon: Building2,
    phase: 2,
    permission: "organizations:read",
  },
  { label: "Countries", path: "/countries", icon: Globe2, phase: 2, permission: "countries:read" },
  { label: "Employees", path: "/employees", icon: Users, phase: 2, permission: "employees:read" },
  { label: "Customers", path: "/customers", icon: UserRound, phase: 3, permission: "customers:read" },
  { label: "Accounts", path: "/accounts", icon: Banknote, phase: 3, permission: "accounts:read" },
  { label: "Retail Banking", path: "/retail", icon: PiggyBank, phase: 29, permission: "accounts:read" },
  { label: "Cards", path: "/cards", icon: CreditCard, phase: 31, permission: "accounts:read" },
  { label: "Payments", path: "/payments", icon: ArrowLeftRight, phase: 9, permission: "payments:read" },
  { label: "Foreign Exchange", path: "/fx", icon: CandlestickChart, phase: 24, permission: "payments:read" },
  { label: "Lending", path: "/lending", icon: HandCoins, phase: 9, permission: "loans:read" },
  {
    label: "Workflow Explorer",
    path: "/workflows",
    icon: Workflow,
    phase: 4,
    permission: "workflows:read",
  },
  {
    label: "Simulation Center",
    path: "/simulations",
    icon: PlayCircle,
    phase: 5,
    permission: "simulations:read",
  },
  { label: "AI Innovation Lab", path: "/ai-lab", icon: Bot, phase: 6, permission: "ai_tools:read" },
  {
    label: "Experiments",
    path: "/experiments",
    icon: FlaskConical,
    phase: 7,
    permission: "experiments:read",
  },
  {
    label: "Benchmarking",
    path: "/benchmarking",
    icon: Gauge,
    phase: 7,
    permission: "experiments:read",
  },
  { label: "Audit Center", path: "/audit", icon: ScrollText, phase: 2, permission: "audit:read" },
  { label: "System Settings", path: "/settings", icon: Settings, phase: 8 },
];

