import { configureStore } from "@reduxjs/toolkit";

import authReducer from "../features/auth/authSlice";
import { payplanApi } from "../app/api";

export function makeStore(preloadedState) {
  return configureStore({
    reducer: {
      auth: authReducer,
      [payplanApi.reducerPath]: payplanApi.reducer,
    },
    preloadedState,
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware().concat(payplanApi.middleware),
  });
}

export const store = makeStore();
