import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";

import { logout, setCredentials } from "../features/auth/authSlice";

const rawBaseQuery = fetchBaseQuery({
  baseUrl: "/api",
  prepareHeaders: (headers, { getState }) => {
    const token = getState().auth.accessToken;
    if (token) headers.set("authorization", `Bearer ${token}`);
    return headers;
  },
});

let refreshInFlight = null;

async function refreshAccessToken(api, refreshToken) {
  if (!refreshInFlight) {
    refreshInFlight = fetch("/api/auth/token/refresh/", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh: refreshToken }),
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("refresh failed");
        return response.json();
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

async function baseQueryWithReauth(args, api, extraOptions) {
  let result = await rawBaseQuery(args, api, extraOptions);
  if (result.error?.status === 401) {
    const { refreshToken } = api.getState().auth;
    if (!refreshToken) return result;
    try {
      const data = await refreshAccessToken(api, refreshToken);
      api.dispatch(
        setCredentials({
          accessToken: data.access,
          refreshToken: data.refresh || refreshToken,
        }),
      );
      result = await rawBaseQuery(args, api, extraOptions);
    } catch {
      api.dispatch(logout());
    }
  }
  return result;
}

export const payplanApi = createApi({
  reducerPath: "payplanApi",
  baseQuery: baseQueryWithReauth,
  tagTypes: ["Me", "Plans", "Plan", "Installments", "Payments", "OpsMember"],
  endpoints: (builder) => ({
    login: builder.mutation({
      query: (credentials) => ({
        url: "/auth/token/",
        method: "POST",
        body: credentials,
      }),
      async onQueryStarted(_arg, { dispatch, queryFulfilled }) {
        const { data } = await queryFulfilled;
        dispatch(
          setCredentials({
            accessToken: data.access,
            refreshToken: data.refresh,
          }),
        );
      },
    }),
    getMe: builder.query({
      query: () => "/members/me/",
      providesTags: ["Me"],
    }),
    getPlans: builder.query({
      query: () => "/plans/",
      providesTags: ["Plans"],
    }),
    getPlan: builder.query({
      query: (id) => `/plans/${id}/`,
      providesTags: (_result, _error, id) => [{ type: "Plan", id }, "Installments"],
    }),
    getPayments: builder.query({
      query: ({ status, page = 1 } = {}) => ({
        url: "/payments/",
        params: { ...(status ? { status } : {}), page },
      }),
      providesTags: ["Payments"],
    }),
    createPayment: builder.mutation({
      query: ({ installment, idempotencyKey }) => ({
        url: "/payments/",
        method: "POST",
        body: { installment },
        headers: { "Idempotency-Key": idempotencyKey },
      }),
      invalidatesTags: ["Me", "Plans", "Plan", "Installments", "Payments"],
    }),
    opsSearchMembers: builder.query({
      query: (q) => ({ url: "/ops/members/", params: { q } }),
      providesTags: ["OpsMember"],
    }),
    opsGetMember: builder.query({
      query: (id) => `/ops/members/${id}/`,
      providesTags: (_result, _error, id) => [{ type: "OpsMember", id }],
    }),
    opsGetAudit: builder.query({
      query: (id) => `/ops/members/${id}/audit/`,
      providesTags: (_result, _error, id) => [{ type: "OpsMember", id }],
    }),
    opsWaiveInstallment: builder.mutation({
      query: ({ id, reason }) => ({
        url: `/ops/installments/${id}/waive/`,
        method: "POST",
        body: { reason },
      }),
      invalidatesTags: ["OpsMember", "Plan", "Plans", "Me", "Installments"],
    }),
    opsRescheduleInstallment: builder.mutation({
      query: ({ id, dueDate, reason }) => ({
        url: `/ops/installments/${id}/reschedule/`,
        method: "POST",
        body: { due_date: dueDate, reason },
      }),
      invalidatesTags: ["OpsMember", "Plan", "Plans", "Me", "Installments"],
    }),
    opsAdjustLimit: builder.mutation({
      query: ({ id, limitCents, reason }) => ({
        url: `/ops/members/${id}/limit/`,
        method: "POST",
        body: { limit_cents: limitCents, reason },
      }),
      invalidatesTags: ["OpsMember", "Me", "Plans"],
    }),
  }),
});

export const {
  useLoginMutation,
  useGetMeQuery,
  useLazyGetMeQuery,
  useGetPlansQuery,
  useGetPlanQuery,
  useGetPaymentsQuery,
  useCreatePaymentMutation,
  useOpsSearchMembersQuery,
  useOpsGetMemberQuery,
  useOpsGetAuditQuery,
  useOpsWaiveInstallmentMutation,
  useOpsRescheduleInstallmentMutation,
  useOpsAdjustLimitMutation,
} = payplanApi;
