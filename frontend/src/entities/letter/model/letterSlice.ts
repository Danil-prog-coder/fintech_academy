import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

import { type LetterFilter, type LetterFolder } from './types';

interface LetterState {
  folder: LetterFolder;
  filter: LetterFilter;
  search: string;
  selectedLetterId: string | null;
  starredIds: string[];
}

const initialState: LetterState = {
  folder: 'inbox',
  filter: 'all',
  search: '',
  selectedLetterId: 'm-petrova',
  starredIds: [],
};

export const letterSlice = createSlice({
  name: 'letter',
  initialState,
  reducers: {
    folderSelected: (state, action: PayloadAction<LetterFolder>) => {
      state.folder = action.payload;
      state.selectedLetterId = null;
    },
    filterChanged: (state, action: PayloadAction<LetterFilter>) => {
      state.filter = action.payload;
    },
    searchChanged: (state, action: PayloadAction<string>) => {
      state.search = action.payload;
    },
    letterSelected: (state, action: PayloadAction<string | null>) => {
      state.selectedLetterId = action.payload;
      if (action.payload) {
        state.folder = 'inbox';
      }
    },
    starToggled: (state, action: PayloadAction<string>) => {
      const id = action.payload;
      state.starredIds = state.starredIds.includes(id)
        ? state.starredIds.filter((item) => item !== id)
        : [...state.starredIds, id];
    },
  },
  selectors: {
    selectFolder: (state) => state.folder,
    selectFilter: (state) => state.filter,
    selectSearch: (state) => state.search,
    selectSelectedLetterId: (state) => state.selectedLetterId,
    selectStarredIds: (state) => state.starredIds,
  },
});

export const { folderSelected, filterChanged, searchChanged, letterSelected, starToggled } =
  letterSlice.actions;

export const {
  selectFolder,
  selectFilter,
  selectSearch,
  selectSelectedLetterId,
  selectStarredIds,
} = letterSlice.selectors;
