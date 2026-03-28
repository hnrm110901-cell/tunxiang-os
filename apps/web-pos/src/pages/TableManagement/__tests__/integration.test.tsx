/**
 * æºè½æ¡å°å¡çç³»ç» - éææµè¯
 * @module pages/TableManagement/__tests__/integration.test.tsx
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/lib/locale/zh_CN';
import TableManagementPage from '../index';
import { useTableStore } from '../../../stores/tableStore';

// Mock API
global.fetch = jest.fn();

describe('TableManagementPage Integration Tests', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useTableStore.setState({
      tables: [],
      summary: null,
      mealPeriod: '',
      viewMode: 'card',
      loading: false,
      error: null,
      currentStoreId: null,
      statusFilter: null,
    });
  });

  it('åºè¯¥æ­£ç¡®æ¸²æä¸»é¡µé¢', () => {
    render(
      <ConfigProvider locale={zhCN}>
        <TableManagementPage storeId="store-001" />
      </ConfigProvider>
    );

    // æ£æ¥ä¸»è¦åç´ æ¯å¦å­å¨
    expect(screen.getByText('å¡ç')).toBeInTheDocument();
    expect(screen.getByText('åè¡¨')).toBeInTheDocument();
    expect(screen.getByText('å°å¾')).toBeInTheDocument();
  });

  it('åºè¯¥å è½½å¹¶æ¾ç¤ºæ¡å°æ°æ®', async () => {
    const mockResponse = {
      ok: true,
      data: {
        summary: {
          empty: 5,
          dining: 3,
          reserved: 1,
          pending_checkout: 1,
          pending_cleanup: 0,
        },
        meal_period: 'lunch',
        tables: [
          {
            table_no: 'A01',
            area: 'å¤§å',
            seats: 4,
            status: 'dining',
            layout: {
              pos_x: 45,
              pos_y: 30,
              width: 8,
              height: 8,
              shape: 'rect' as const,
            },
            card_fields: [
              {
                key: 'amount',
                label: 'æ¶è´¹',
                value: 'Â¥680',
                priority: 80,
                alert: 'normal' as const,
              },
            ],
          },
        ],
      },
    };

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockResponse,
    });

    render(
      <ConfigProvider locale={zhCN}>
        <TableManagementPage storeId="store-001" />
      </ConfigProvider>
    );

    // ç­å¾æ°æ®å è½½
    await waitFor(() => {
      expect(screen.getByText('A01')).toBeInTheDocument();
    });

    // éªè¯æ±æ»æ°æ®
    expect(screen.getByText('ç©ºå°')).toBeInTheDocument();
    expect(screen.getByText('ç¨é¤ä¸­')).toBeInTheDocument();
  });

  it('åºè¯¥æ¯æè§å¾åæ¢', async () => {
    render(
      <ConfigProvider locale={zhCN}>
        <TableManagementPage storeId="store-001" />
      </ConfigProvider>
    );

    const listButton = screen.getByText('åè¡¨');
    fireEvent.click(listButton);

    await waitFor(() => {
      expect(useTableStore.getState().viewMode).toBe('list');
    });
  });

  it('åºè¯¥æ­£ç¡®å¤çAPIéè¯¯', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('API Error'));

    render(
      <ConfigProvider locale={zhCN}>
        <TableManagementPage storeId="store-001" />
      </ConfigProvider>
    );

    await waitFor(() => {
      const state = useTableStore.getState();
      expect(state.error).toBeTruthy();
    });
  });

  it('åºè¯¥æ¯æç¶æç­é', async () => {
    useTableStore.setState({
      tables: [
        {
          table_no: 'A01',
          area: 'å¤§å',
          seats: 4,
          status: 'dining' as const,
          layout: {
            pos_x: 45,
            pos_y: 30,
            width: 8,
            height: 8,
            shape: 'rect' as const,
          },
          card_fields: [],
        },
        {
          table_no: 'A02',
          area: 'å¤§å',
          seats: 4,
          status: 'empty' as const,
          layout: {
            pos_x: 50,
            pos_y: 30,
            width: 8,
            height: 8,
            shape: 'rect' as const,
          },
          card_fields: [],
        },
      ],
      summary: {
        empty: 1,
        dining: 1,
        reserved: 0,
        pending_checkout: 0,
        pending_cleanup: 0,
      },
    });

    render(
      <ConfigProvider locale={zhCN}>
        <TableManagementPage storeId="store-001" />
      </ConfigProvider>
    );

    // ç¹å»ç­éæé®
    const diningItem = screen.getByText('ç¨é¤ä¸­');
    fireEvent.click(diningItem);

    await waitFor(() => {
      const filtered = useTableStore.getState().getFilteredTables();
      expect(filtered).toHaveLength(1);
      expect(filtered[0].table_no).toBe('A01');
    });
  });

  it('åºè¯¥æ­£ç¡®è®°å½å­æ®µç¹å»äºä»¶', async () => {
    const trackPayload = {
      ok: true,
      message: 'tracked',
    };

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => trackPayload,
    });

    const { trackFieldClick } = useTableStore.getState();
    await trackFieldClick('store-001', 'A01', 'amount', 'æ¶è´¹');

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/tables/click-track',
      expect.objectContaining({
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      })
    );
  });

  it('åºè¯¥å¨ç©ºæ°æ®æ¶æ¾ç¤ºç©ºç¶ææç¤º', async () => {
    useTableStore.setState({
      tables: [],
      loading: false,
    });

    render(
      <ConfigProvider locale={zhCN}>
        <TableManagementPage storeId="store-001" />
      </ConfigProvider>
    );

    expect(screen.getByText('ææ æ¡å°æ°æ®')).toBeInTheDocument();
  });

  it('åºè¯¥æ¾ç¤ºå è½½ç¶æ', () => {
    useTableStore.setState({
      loading: true,
    });

    render(
      <ConfigProvider locale={zhCN}>
        <TableManagementPage storeId="store-001" />
      </ConfigProvider>
    );

    expect(screen.getByText('å è½½ä¸­...')).toBeInTheDocument();
  });
});
