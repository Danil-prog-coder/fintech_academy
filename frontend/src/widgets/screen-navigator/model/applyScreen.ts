import { createAsyncThunk } from '@reduxjs/toolkit';

import { draftsReset, draftTextChanged, selectDraft } from '@/entities/draft';
import { filterChanged, letterSelected, searchChanged } from '@/entities/letter';
import {
  searchPanelOpened,
  searchRestored,
  searchSubmitted,
  showSearchResult,
} from '@/features/ai-search';
import { versionPickerClosed, versionPickerOpened } from '@/features/choose-attachment-version';
import { connectionsRestored } from '@/features/connect-source';
import {
  allAiRepliesReset,
  demoScenarioChanged,
  panelCollapsedChanged,
  prepareReply,
  type DemoScenario,
} from '@/features/prepare-reply';
import { allRefinesReset, refineFailureSimulated, refineReply } from '@/features/refine-reply';

import { type ScreenId } from '../config/screens';

const MAIN_LETTER = 'm-petrova';
const EXTERNAL_LETTER = 'm-client';

interface ThunkConfig {
  state: RootState;
  dispatch: AppDispatch;
}

/**
 * Приводит приложение в состояние конкретного экрана из макетов.
 * Используются те же действия, что и при обычной работе пользователя.
 */
export const applyScreen = createAsyncThunk<undefined, ScreenId, ThunkConfig>(
  'screenNavigator/apply',
  async (screen, { dispatch, getState }) => {
    const resetMail = (letterId = MAIN_LETTER) => {
      dispatch(
        connectionsRestored({ mail: 'connected', documents: 'connected', policy: 'allowed' }),
      );
      dispatch(draftsReset());
      dispatch(allAiRepliesReset());
      dispatch(allRefinesReset());
      dispatch(versionPickerClosed());
      dispatch(searchRestored({ open: false, request: null, caveatAccepted: false }));
      dispatch(demoScenarioChanged('complete'));
      dispatch(filterChanged('all'));
      dispatch(searchChanged(''));
      dispatch(letterSelected(letterId));
    };

    const prepared = async (scenario: DemoScenario = 'complete') => {
      resetMail();
      dispatch(demoScenarioChanged(scenario));
      await dispatch(prepareReply({ letterId: MAIN_LETTER, instant: true }));
    };

    const searchResult = async (query: string) => {
      await prepared();
      await dispatch(showSearchResult({ query, context: [], attempt: 0 }));
    };

    switch (screen) {
      case 'S01':
        resetMail();
        break;
      case 'S02':
        resetMail();
        void dispatch(prepareReply({ letterId: MAIN_LETTER }));
        break;
      case 'S03':
        await prepared('complete');
        break;
      case 'S04':
        await prepared('partial');
        break;
      case 'S05':
        await prepared('complete');
        dispatch(versionPickerOpened(MAIN_LETTER));
        break;
      case 'S06':
        await prepared('facts');
        break;
      case 'S07': {
        await prepared('complete');
        const text = selectDraft(getState(), MAIN_LETTER)?.text ?? '';
        dispatch(
          draftTextChanged({
            letterId: MAIN_LETTER,
            text: `${text}\n\nПредлагаю обсудить детали во вторник.`,
          }),
        );
        await dispatch(
          refineReply({
            letterId: MAIN_LETTER,
            query: 'Сделай первый абзац короче',
            instant: true,
          }),
        );
        break;
      }
      case 'S08':
        await prepared('complete');
        dispatch(panelCollapsedChanged(true));
        break;
      case 'S09':
        await prepared('complete');
        dispatch(searchPanelOpened());
        break;
      case 'S10':
        await prepared('complete');
        dispatch(searchPanelOpened());
        dispatch(searchSubmitted({ query: 'Где финансовая смета проекта?' }));
        break;
      case 'S11':
        await searchResult('Где финансовая смета проекта?');
        break;
      case 'S12':
        await searchResult('Найди финальную презентацию');
        break;
      case 'S13':
        await searchResult('Кто окончательно согласовал бюджет?');
        break;
      case 'S14':
        await searchResult('Найди согласование договора');
        break;
      case 'S15':
        dispatch(
          connectionsRestored({
            mail: 'not_connected',
            documents: 'not_connected',
            policy: 'allowed',
          }),
        );
        break;
      case 'S16':
        dispatch(
          connectionsRestored({ mail: 'connected', documents: 'connected', policy: 'allowed' }),
        );
        break;
      case 'S17':
        dispatch(
          connectionsRestored({
            mail: 'forbidden',
            documents: 'not_connected',
            policy: 'forbidden',
          }),
        );
        break;
      case 'S18':
        dispatch(
          connectionsRestored({ mail: 'auth_required', documents: 'connected', policy: 'allowed' }),
        );
        break;
      case 'S19':
      case 'S20':
      case 'S21':
      case 'S22':
      case 'S23':
        break;
      case 'S24':
        await prepared('conflict');
        break;
      case 'S25':
        resetMail(EXTERNAL_LETTER);
        await dispatch(prepareReply({ letterId: EXTERNAL_LETTER, instant: true }));
        break;
      case 'S26':
        await prepared('complete');
        dispatch(refineFailureSimulated(true));
        await dispatch(
          refineReply({
            letterId: MAIN_LETTER,
            query: 'Сделай первый абзац короче',
            instant: true,
          }),
        );
        break;
    }
  },
);
