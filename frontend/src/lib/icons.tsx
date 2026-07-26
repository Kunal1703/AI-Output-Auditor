/**
 * Icon registry — maps the string icon keys used across `format.ts` and the UI
 * to concrete lucide-react components, so display metadata stays JSX-free and
 * icons are consistent everywhere.
 */

import {
  BookOpen,
  Bot,
  CheckCircle2,
  CircleDot,
  CircleHelp,
  GitCompare,
  Hash,
  HelpCircle,
  Layers,
  Pencil,
  Scale,
  Scissors,
  ShieldCheck,
  ThumbsUp,
  User,
  XOctagon,
  type LucideIcon,
} from 'lucide-react';
import { cn } from './cn';

const REGISTRY: Record<string, LucideIcon> = {
  'check-circle': CheckCircle2,
  'thumbs-up': ThumbsUp,
  pencil: Pencil,
  'x-octagon': XOctagon,
  'help-circle': HelpCircle,
  'shield-check': ShieldCheck,
  hash: Hash,
  layers: Layers,
  'git-compare': GitCompare,
  'book-open': BookOpen,
  scissors: Scissors,
  scale: Scale,
  'circle-dot': CircleDot,
  user: User,
  bot: Bot,
  'circle-help': CircleHelp,
};

export function Icon({
  name,
  className,
  size = 16,
  strokeWidth = 2,
}: {
  name: string;
  className?: string;
  size?: number;
  strokeWidth?: number;
}) {
  const Cmp = REGISTRY[name] ?? CircleDot;
  return <Cmp size={size} strokeWidth={strokeWidth} className={cn(className)} aria-hidden />;
}
