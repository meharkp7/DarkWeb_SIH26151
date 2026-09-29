import { describe, expect, it } from 'vitest';
import { ApiError, api, formatApiError, getJson } from './client';
import { installFetch, jsonResponse, nonJsonResponse } from '../test/mockFetch';

async function captureError(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
    return null;
  } catch (error: unknown) {
    return error;
  }
}

describe('api client', () => {
  it('updateCase issues a PATCH to the case URL with the partial payload', async () => {
    const fetchMock = installFetch(async () =>
      jsonResponse({ case_id: 'case-1', name: 'Phantom', status: 'closed' }),
    );

    await expect(
      api.updateCase('case-1', { status: 'closed', closure_reason: 'No threat. Watch only.' }),
    ).resolves.toMatchObject({ case_id: 'case-1' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/cases/case-1');
    expect(init.method).toBe('PATCH');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body as string)).toEqual({
      status: 'closed',
      closure_reason: 'No threat. Watch only.',
    });
  });

  it('updateCase URL-encodes the case id', async () => {
    const fetchMock = installFetch(async () => jsonResponse({}));

    await api.updateCase('case/1', { priority: 'high' }).catch(() => undefined);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe('/api/v1/cases/case%2F1');
  });

  it('getJson requests JSON and resolves the parsed body', async () => {
    const fetchMock = installFetch(async () => jsonResponse({ hello: 'world' }));

    await expect(getJson('/api/v1/cases')).resolves.toEqual({ hello: 'world' });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/cases');
    expect(init.method).toBeUndefined(); // GET by default
    expect((init.headers as Record<string, string>)['Accept']).toBe('application/json');
  });

  it('surfaces the server’s string error detail', async () => {
    installFetch(async () =>
      jsonResponse({ detail: 'Down for maintenance' }, { status: 503, statusText: 'Service Unavailable' }),
    );

    const error = await captureError(getJson('/api/v1/cases'));
    expect(error).toBeInstanceOf(ApiError);
    if (error instanceof ApiError) {
      expect(error.status).toBe(503);
      expect(error.detail).toBe('Down for maintenance');
      expect(error.message).toBe('API request failed (503): Down for maintenance');
    }
    expect(formatApiError(error)).toBe('API 503 — Down for maintenance');
  });

  it('surfaces the first message from a FastAPI validation-error list', async () => {
    installFetch(async () =>
      jsonResponse(
        {
          detail: [
            { loc: ['body', 'name'], msg: 'Field required', type: 'missing' },
            { loc: ['body', 'severity'], msg: 'Input should be a valid enum', type: 'enum' },
          ],
        },
        { status: 422, statusText: 'Unprocessable Entity' },
      ),
    );

    const error = await captureError(getJson('/api/v1/cases'));
    expect(error).toBeInstanceOf(ApiError);
    if (error instanceof ApiError) {
      expect(error.status).toBe(422);
      expect(error.detail).toBe('Field required');
    }
  });

  it('falls back to the HTTP status text when the error body is not JSON', async () => {
    installFetch(async () => nonJsonResponse(502, 'Bad Gateway'));

    const error = await captureError(getJson('/api/v1/cases'));
    expect(error).toBeInstanceOf(ApiError);
    if (error instanceof ApiError) {
      expect(error.detail).toBe('Bad Gateway');
    }
    expect(formatApiError(error)).toBe('API 502 — Bad Gateway');
  });

  it('formatApiError maps TypeError, plain Error and unknown to stable copy', () => {
    expect(formatApiError(new TypeError('network down'))).toBe('Cannot reach the AEGIS API.');
    expect(formatApiError(new Error('boom'))).toBe('boom');
    expect(formatApiError('not an error')).toBe('Unexpected API error.');
    expect(formatApiError(new ApiError(401, 'unauthorized'))).toBe('API 401 — unauthorized');
  });
});