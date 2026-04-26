import { BrowserRouter } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { AppRouter } from './router'

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <AppRouter />
      </Layout>
    </BrowserRouter>
  )
}
