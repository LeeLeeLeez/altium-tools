import { Card, CardBody, CardHeader, Page, PageHeader, Text } from 'oink-ui'

import type { PageProps } from '../types'

/** 原理图操作 —— 目前是占位页。 */
export default function OverviewPage(_props: PageProps) {
  return (
    <Page size="full">
      <PageHeader
        title="原理图操作"
        description="本分类下的功能待添加。"
      />
      <Card>
        <CardHeader title="规划中的功能" />
        <CardBody>
          <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.9 }}>
            <li>
              <Text variant="body">符号 / 器件批量处理</Text>
            </li>
            <li>
              <Text variant="body">网络与连线检查</Text>
            </li>
            <li>
              <Text variant="body">参数表导入导出</Text>
            </li>
          </ul>
          <div className="stack-gap" />
          <Text variant="caption" tone="subtle">
            新增页面：在 App.tsx 的 NAV 里加一项，再写一个 pages/XxxPage.tsx。
          </Text>
        </CardBody>
      </Card>
    </Page>
  )
}
