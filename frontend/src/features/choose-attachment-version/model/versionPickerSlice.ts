import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

interface VersionPickerState {
  /** Письмо, для черновика которого выбирается версия вложения. */
  letterId: string | null;
}

const initialState: VersionPickerState = {
  letterId: null,
};

export const versionPickerSlice = createSlice({
  name: 'versionPicker',
  initialState,
  reducers: {
    versionPickerOpened: (state, action: PayloadAction<string>) => {
      state.letterId = action.payload;
    },
    versionPickerClosed: (state) => {
      state.letterId = null;
    },
  },
  selectors: {
    selectVersionPickerLetterId: (state) => state.letterId,
  },
});

export const { versionPickerOpened, versionPickerClosed } = versionPickerSlice.actions;
export const { selectVersionPickerLetterId } = versionPickerSlice.selectors;
