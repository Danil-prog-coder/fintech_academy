import { createAsyncThunk } from '@reduxjs/toolkit';

import { getDocumentById, toAttachment } from '@/entities/document';
import {
  draftAttachmentSet,
  draftEnsured,
  draftTextChanged,
  selectDraft,
  type Recipient,
} from '@/entities/draft';
import { letterApi, type Letter } from '@/entities/letter';
import { delay } from '@/shared/lib/time';

import {
  preparationFailed,
  preparationStarted,
  preparationSucceeded,
  stepAdvanced,
} from './aiReplySlice';
import { PREPARATION_STEPS, resolveScenario, scenarioContent } from '../config/scenarios';

interface PrepareReplyArgs {
  letterId: string;
  /** Без имитации задержек (для навигатора по экранам). */
  instant?: boolean;
}

const loadLetter = async (dispatch: AppDispatch, letterId: string): Promise<Letter | undefined> => {
  const request = dispatch(letterApi.endpoints.getLetter.initiate(letterId));
  try {
    return await request.unwrap();
  } catch {
    return undefined;
  } finally {
    request.unsubscribe();
  }
};

/**
 * Один запуск — один черновик в обычном редакторе письма.
 * AI не отправляет письмо и не меняет адресатов; ручной текст сохраняется.
 */
export const prepareReply = createAsyncThunk<
  undefined,
  PrepareReplyArgs,
  { state: RootState; dispatch: AppDispatch }
>(
  'aiReply/prepare',
  async ({ letterId, instant = false }, { dispatch, getState }) => {
    dispatch(preparationStarted({ letterId }));

    const letter = await loadLetter(dispatch, letterId);
    if (!letter) {
      dispatch(preparationFailed({ letterId }));
      return;
    }

    const to: Recipient[] = [
      { name: letter.from.name, email: letter.from.email, external: Boolean(letter.from.external) },
    ];
    dispatch(draftEnsured({ letterId, to }));

    if (!instant) {
      for (const [index, step] of PREPARATION_STEPS.entries()) {
        dispatch(stepAdvanced({ letterId, step: index }));
        await delay(step.durationMs);
      }
    }

    const scenario = resolveScenario(letterId, getState().aiReply.demoScenario);
    if (scenario === 'error') {
      dispatch(preparationFailed({ letterId }));
      return;
    }

    const content = scenarioContent[scenario];
    const firstName = letter.from.name.split(' ')[0] ?? letter.from.name;
    const aiText = content.text(firstName);
    const manualText = selectDraft(getState(), letterId)?.text.trim() ?? '';
    dispatch(
      draftTextChanged({
        letterId,
        text: manualText ? `${aiText}\n\n${manualText}` : aiText,
      }),
    );

    const document = content.attachmentId ? getDocumentById(content.attachmentId) : undefined;
    if (document) {
      dispatch(
        draftAttachmentSet({
          letterId,
          attachment: toAttachment(document, {
            externalRecipient: to.some((recipient) => recipient.external),
          }),
        }),
      );
    }

    dispatch(preparationSucceeded({ letterId, scenario }));
  },
  {
    // Запрет двойного запуска.
    condition: ({ letterId }, { getState }) =>
      getState().aiReply.byLetter[letterId]?.status !== 'preparing',
  },
);
