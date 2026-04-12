/**
 * 文档上传页 — 上传新文档到知识库
 */
import { useState } from 'react';
import { Card, Upload, Button, Input, Select, Typography, Space, Tag, message } from 'antd';
import {
  UploadOutlined,
  InboxOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

const { TextArea } = Input;
const { Dragger } = Upload;
const { Text } = Typography;

const C = {
  primary: '#FF6B35',
  success: '#0F6E56',
  info: '#185FA5',
  textSub: '#5F5E5A',
  textMuted: '#B4B2A9',
};

const COLLECTIONS = [
  { label: '菜品知识', value: '菜品知识' },
  { label: '运营SOP', value: '运营SOP' },
  { label: '食安标准', value: '食安标准' },
  { label: '培训手册', value: '培训手册' },
  { label: '设备维护', value: '设备维护' },
];

export default function DocumentUploadPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [collection, setCollection] = useState<string | undefined>();
  const [description, setDescription] = useState('');
  const [fileList, setFileList] = useState<any[]>([]);

  const handleUpload = () => {
    if (!title.trim()) {
      message.warning('请输入文档标题');
      return;
    }
    if (!collection) {
      message.warning('请选择知识库集合');
      return;
    }
    if (fileList.length === 0) {
      message.warning('请选择要上传的文件');
      return;
    }
    // TODO: 调用 knowledgeApi.uploadDocument
    message.success('文档上传成功（演示）');
    navigate('/knowledge/documents');
  };

  return (
    <div style={{ padding: 24, maxWidth: 800 }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A' }}>上传文档</h2>
        <Text style={{ fontSize: 13, color: C.textSub }}>
          上传文档到知识库，系统将自动分块并生成向量索引
        </Text>
      </div>

      <Card>
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 600 }}>
            文档标题 <span style={{ color: '#ff4d4f' }}>*</span>
          </label>
          <Input
            placeholder="输入文档标题"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 600 }}>
            知识库集合 <span style={{ color: '#ff4d4f' }}>*</span>
          </label>
          <Select
            placeholder="选择所属集合"
            value={collection}
            onChange={setCollection}
            style={{ width: '100%' }}
            options={COLLECTIONS}
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 600 }}>
            文档描述
          </label>
          <TextArea
            placeholder="简要描述文档内容（可选）"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            maxLength={500}
          />
        </div>

        <div style={{ marginBottom: 24 }}>
          <label style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 600 }}>
            上传文件 <span style={{ color: '#ff4d4f' }}>*</span>
          </label>
          <Dragger
            multiple={false}
            fileList={fileList}
            beforeUpload={(file) => {
              setFileList([file]);
              return false; // 阻止自动上传
            }}
            onRemove={() => setFileList([])}
            accept=".pdf,.docx,.doc,.txt,.md,.csv"
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined style={{ color: C.primary, fontSize: 40 }} />
            </p>
            <p style={{ fontSize: 14, color: '#2C2C2A' }}>
              点击或拖拽文件到此处上传
            </p>
            <p style={{ fontSize: 12, color: C.textMuted }}>
              支持 PDF、Word、TXT、Markdown、CSV 格式，单文件最大 20MB
            </p>
          </Dragger>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
          <Button onClick={() => navigate('/knowledge/documents')}>取消</Button>
          <Button type="primary" icon={<UploadOutlined />} onClick={handleUpload}>
            上传并处理
          </Button>
        </div>
      </Card>
    </div>
  );
}
