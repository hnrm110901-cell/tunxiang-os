import React from 'react';
import AgentConfigPage from '../../AgentConfigPage';

interface Props {
  brandId: string;
  brandName?: string;
}

const AgentConfigTab: React.FC<Props> = ({ brandId, brandName }) => {
  return <AgentConfigPage brandId={brandId} brandName={brandName} />;
};

export default AgentConfigTab;
