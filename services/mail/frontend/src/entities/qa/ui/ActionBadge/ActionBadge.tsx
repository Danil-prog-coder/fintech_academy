import { Badge, type BadgeTone } from '@/shared/ui';

import { actionLabel } from '../../lib/labels';
import { type AnswerAction } from '../../model/types';

const tones: Record<AnswerAction, BadgeTone> = {
  answer: 'success',
  clarify: 'warning',
  offer_operator: 'neutral',
  escalate: 'warning',
};

export const ActionBadge = ({ action }: { action: AnswerAction }) => (
  <Badge tone={tones[action]}>{actionLabel[action]}</Badge>
);
