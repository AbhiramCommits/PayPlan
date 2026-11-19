import { createSlice } from "@reduxjs/toolkit";

const initialState = {
  accessToken: null,
  refreshToken: null,
  member: null,
};

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    setCredentials(state, action) {
      state.accessToken = action.payload.accessToken;
      if (action.payload.refreshToken) {
        state.refreshToken = action.payload.refreshToken;
      }
    },
    setMember(state, action) {
      state.member = action.payload;
    },
    logout(state) {
      state.accessToken = null;
      state.refreshToken = null;
      state.member = null;
    },
  },
});

export const { setCredentials, setMember, logout } = authSlice.actions;
export const selectAuth = (state) => state.auth;
export const selectRoles = (state) => state.auth.member?.roles ?? [];
export default authSlice.reducer;
