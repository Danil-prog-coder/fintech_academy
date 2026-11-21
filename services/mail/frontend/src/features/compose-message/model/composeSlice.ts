import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

/** Начальное содержимое окна написания письма (сериализуемое; файлы живут в самом окне). */
export interface ComposeInit {
  to: string;
  cc: string;
  bcc: string;
  subject: string;
  body: string;
  inReplyTo: string | null;
  references: string | null;
  /** Исходное письмо, которому после отправки ставится флаг «отвечено». */
  answered: { folder: string; uid: number } | null;
  /** Черновик, который удаляется после отправки или повторного сохранения. */
  replaces: { folder: string; uid: number } | null;
  /** Переписка для «Спросить у ИИ»: письма, на которые отвечаем. */
  thread: { author: string | null; text: string; sentAt: string | null }[];
}

interface ComposeState {
  init: ComposeInit | null;
  /** Меняется при каждом открытии, чтобы окно начинало с чистого состояния. */
  seq: number;
}

const initialState: ComposeState = { init: null, seq: 0 };

export const emptyCompose: ComposeInit = {
  to: '',
  cc: '',
  bcc: '',
  subject: '',
  body: '',
  inReplyTo: null,
  references: null,
  answered: null,
  replaces: null,
  thread: [],
};

export const composeSlice = createSlice({
  name: 'compose',
  initialState,
  reducers: {
    composeOpened: (state, action: PayloadAction<ComposeInit>) => {
      state.init = action.payload;
      state.seq += 1;
    },
    composeClosed: (state) => {
      state.init = null;
    },
  },
  selectors: {
    selectComposeInit: (state) => state.init,
    selectComposeSeq: (state) => state.seq,
  },
});

export const { composeOpened, composeClosed } = composeSlice.actions;
export const { selectComposeInit, selectComposeSeq } = composeSlice.selectors;
