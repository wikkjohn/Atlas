import {
  Banknote,
  Bot,
  Building2,
  FlaskConical,
  Gauge,
  Globe2,
  LayoutDashboard,
  type LucideIcon,
  PlayCircle,
  ScrollText,
  Settings,
  UserRound,
  Users,
  Workflow,
} from "lucide-react";

export interface NavItem {
  label: string;
  path: string;
  icon: LucideIcon;
  /** Implementation phase that delivers this screen. */
  phase: number;
}

/** Phase 1 delivers the Overview only. Other entries are shown disabled with their phase. */
export const IMPLEMENTED_PHASE = 1;

export const NAV_ITEMS: NavItem[] = [
  { label: "Overview", path: "/", icon: LayoutDashboard, phase: 1 },
  { label: "Organization", path: "/organization", icon: Building2, phase: 2 },
  { label: "Countries", path: "/countries", icon: Globe2, phase: 2 },
  { label: "Employees", path: "/employees", icon: Users, phase: 2 },
  { label: "Customers", path: "/customers", icon: UserRound, phase: 3 },
  { label: "Accounts", path: "/accounts", icon: Banknote, phase: 3 },
  { label: "Workflow Explorer", path: "/workflows", icon: Workflow, phase: 4 },
  { label: "Simulation Center", path: "/simulations", icon: PlayCircle, phase: 5 },
  { label: "AI Innovation Lab", path: "/ai-lab", icon: Bot, phase: 6 },
  { label: "Experiments", path: "/experiments", icon: FlaskConical, phase: 7 },
  { label: "Benchmarking", path: "/benchmarking", icon: Gauge, phase: 7 },
  { label: "Audit Center", path: "/audit", icon: ScrollText, phase: 2 },
  { label: "System Settings", path: "/settings", icon: Settings, phase: 8 },
];

