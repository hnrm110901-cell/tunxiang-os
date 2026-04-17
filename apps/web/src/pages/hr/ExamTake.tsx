/**
 * 答题页 — D11 Should-Fix P1
 *
 * 功能：
 *   · 倒计时（到点自动提交）
 *   · 题目导航 + 答题卡
 *   · 5 种题型：single / multi / judge / fill / essay
 *   · 自动保存草稿（localStorage，每 30 秒）
 *   · 页面离开次数记入 answers.meta.leave_count
 *
 * 路由：/hr/exam/take/:paperId?attempt={attempt_id}
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Card,
  Button,
  Radio,
  Checkbox,
  Input,
  Modal,
  Space,
  message,
  Progress,
  Tag,
} from 'antd';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import apiClient from '../../services/api';

interface Question {
  id: string;
  type: 'single' | 'multi' | 'judge' | 'fill' | 'essay';
  stem: string;
  options_json?: Array<{ key: string; text: string }>;
  score: number;
}

interface Paper {
  id: string;
  title: string;
  total_score: number;
  pass_score: number;
  duration_min: number;
  questions: Question[];
}

export default function ExamTake() {
  const { paperId } = useParams<{ paperId: string }>();
  const [params] = useSearchParams();
  const attemptId = params.get('attempt') || '';
  const navigate = useNavigate();

  const [paper, setPaper] = useState<Paper | null>(null);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [current, setCurrent] = useState(0);
  const [remainSec, setRemainSec] = useState(0);
  const [leaveCount, setLeaveCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const draftKey = `exam_draft_${attemptId || paperId}`;
  const startRef = useRef<number>(Date.now());

  // 加载试卷
  useEffect(() => {
    (async () => {
      try {
        const resp = await apiClient.get(`/api/v1/hr/training/exam/papers/${paperId}`);
        const p: Paper = resp.data?.data;
        setPaper(p);
        setRemainSec(p.duration_min * 60);
        // 恢复草稿
        const cached = localStorage.getItem(draftKey);
        if (cached) {
          try {
            setAnswers(JSON.parse(cached));
          } catch {}
        }
      } catch (e: any) {
        message.error('试卷加载失败');
      }
    })();
  }, [paperId]);

  // 倒计时
  useEffect(() => {
    if (!paper) return;
    const timer = setInterval(() => {
      setRemainSec((s) => {
        if (s <= 1) {
          clearInterval(timer);
          handleSubmit(true);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [paper]);

  // 防作弊：visibilitychange
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'hidden') {
        setLeaveCount((n) => n + 1);
      }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  // 自动保存草稿 30s
  useEffect(() => {
    const id = setInterval(() => {
      localStorage.setItem(draftKey, JSON.stringify(answers));
    }, 30000);
    return () => clearInterval(id);
  }, [answers, draftKey]);

  const setAnswer = (qid: string, value: any) => {
    setAnswers((prev) => ({ ...prev, [qid]: value }));
  };

  const handleSubmit = async (auto = false) => {
    if (submitting || !attemptId) {
      if (!attemptId) message.error('缺少 attempt_id，无法提交');
      return;
    }
    const doSubmit = async () => {
      setSubmitting(true);
      try {
        const payload = {
          ...answers,
          meta: { leave_count: leaveCount, auto_submit: auto, client_ms: Date.now() - startRef.current },
        };
        const resp = await apiClient.post(`/api/v1/hr/training/exam/attempts/${attemptId}/submit`, {
          answers: payload,
        });
        const data = resp.data?.data;
        localStorage.removeItem(draftKey);
        message.success(`提交成功：${data?.score ?? 0} 分，${data?.passed ? '通过' : '未通过'}`);
        navigate(`/hr/exam/result/${attemptId}`);
      } catch (e: any) {
        message.error(e?.response?.data?.detail || '提交失败');
      } finally {
        setSubmitting(false);
      }
    };
    if (auto) {
      doSubmit();
    } else {
      Modal.confirm({
        title: '确认交卷？',
        content: '交卷后不可修改答案。',
        onOk: doSubmit,
      });
    }
  };

  const answered = useMemo(() => Object.keys(answers).filter((k) => k !== 'meta').length, [answers]);

  if (!paper) return <div style={{ padding: 24 }}>加载中…</div>;

  const q = paper.questions[current];

  const renderQuestion = (q: Question) => {
    const val = answers[q.id];
    switch (q.type) {
      case 'single':
        return (
          <Radio.Group value={val} onChange={(e) => setAnswer(q.id, e.target.value)}>
            <Space direction="vertical">
              {(q.options_json || []).map((o) => (
                <Radio key={o.key} value={o.key}>
                  {o.key}. {o.text}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        );
      case 'multi':
        return (
          <Checkbox.Group value={val || []} onChange={(v) => setAnswer(q.id, v)}>
            <Space direction="vertical">
              {(q.options_json || []).map((o) => (
                <Checkbox key={o.key} value={o.key}>
                  {o.key}. {o.text}
                </Checkbox>
              ))}
            </Space>
          </Checkbox.Group>
        );
      case 'judge':
        return (
          <Radio.Group value={val} onChange={(e) => setAnswer(q.id, e.target.value)}>
            <Radio value={true}>正确</Radio>
            <Radio value={false}>错误</Radio>
          </Radio.Group>
        );
      case 'fill':
        return (
          <Input
            value={val || ''}
            onChange={(e) => setAnswer(q.id, e.target.value)}
            placeholder="请输入答案"
            style={{ maxWidth: 400 }}
          />
        );
      case 'essay':
        return (
          <Input.TextArea
            rows={6}
            value={val || ''}
            onChange={(e) => setAnswer(q.id, e.target.value)}
            placeholder="请作答（主观题，老师批改）"
          />
        );
      default:
        return null;
    }
  };

  const mm = String(Math.floor(remainSec / 60)).padStart(2, '0');
  const ss = String(remainSec % 60).padStart(2, '0');

  return (
    <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '1fr 260px', gap: 16 }}>
      <Card
        title={paper.title}
        extra={
          <Space>
            <Tag color={remainSec < 60 ? 'red' : 'blue'}>
              剩余 {mm}:{ss}
            </Tag>
            <Tag>
              已答 {answered}/{paper.questions.length}
            </Tag>
          </Space>
        }
      >
        {q && (
          <>
            <div style={{ marginBottom: 8, color: '#999' }}>
              第 {current + 1} / {paper.questions.length} 题 · {q.type} · {q.score} 分
            </div>
            <div style={{ fontSize: 16, marginBottom: 16, whiteSpace: 'pre-wrap' }}>{q.stem}</div>
            {renderQuestion(q)}
            <div style={{ marginTop: 24 }}>
              <Space>
                <Button disabled={current === 0} onClick={() => setCurrent(current - 1)}>
                  上一题
                </Button>
                <Button
                  disabled={current === paper.questions.length - 1}
                  onClick={() => setCurrent(current + 1)}
                >
                  下一题
                </Button>
                <Button type="primary" loading={submitting} onClick={() => handleSubmit(false)}>
                  交卷
                </Button>
              </Space>
            </div>
          </>
        )}
      </Card>

      <Card title="答题卡" size="small">
        <Progress percent={Math.round((answered / paper.questions.length) * 100)} />
        <div
          style={{
            marginTop: 12,
            display: 'grid',
            gridTemplateColumns: 'repeat(5, 1fr)',
            gap: 6,
          }}
        >
          {paper.questions.map((qq, idx) => {
            const done = answers[qq.id] !== undefined && answers[qq.id] !== '';
            return (
              <Button
                key={qq.id}
                size="small"
                type={current === idx ? 'primary' : 'default'}
                style={{ background: done && current !== idx ? '#f6ffed' : undefined }}
                onClick={() => setCurrent(idx)}
              >
                {idx + 1}
              </Button>
            );
          })}
        </div>
        <div style={{ marginTop: 12, fontSize: 12, color: '#999' }}>
          离开次数：{leaveCount}（记录在答卷 meta）
        </div>
      </Card>
    </div>
  );
}
