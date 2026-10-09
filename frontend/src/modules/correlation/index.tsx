import { useParams } from 'react-router-dom'
import { Card, Chip, PageHeader, Tabs } from '../../ui'
import { CameraMap } from './CameraMap'
import { ExternalLogs } from './ExternalLogs'
import { SUGGESTION_LABEL, SuggestedLinks } from './Links'

export default function CorrelationModule() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader
        title="Link suggestions"
        subtitle={<span className="inline-flex flex-wrap items-center gap-2"><Chip tone="info">{SUGGESTION_LABEL}</Chip> Reference test data only.</span>}
      />
      <Card>
        <Tabs
          label="Correlation"
          tabs={[
            { id: 'links', label: 'Suggested links', render: () => <SuggestedLinks caseId={caseId} /> },
            { id: 'map', label: 'Camera map', render: () => <CameraMap caseId={caseId} /> },
            { id: 'logs', label: 'External logs', render: () => <ExternalLogs caseId={caseId} /> },
          ]}
        />
      </Card>
    </div>
  )
}
