import { Badge, type BadgeTone } from '@/shared/ui';

import { answerStatusLabel } from '../../lib/labels';
import { type AnswerStatus } from '../../model/types';

const tones: Record<AnswerStatus, BadgeTone> = {
  answered: 'success',
  partial: 'warning',
  not_found: 'neutral',
  out_of_scope: 'neutral',
};

export const AnswerStatusBadge = ({ status }: { status: AnswerStatus }) => (
  <Badge tone={tones[status]}>{answerStatusLabel[status]}</Badge>
);
