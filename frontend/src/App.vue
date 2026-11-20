<template>
  <div class="app-wrapper">
    <!-- Header -->
    <header class="main-header">
      <div class="logo">
      </div>
      <div class="header-status" v-if="videoTitle">
        <el-tag :type="statusType" effect="dark" round>
          {{ statusLabel }}
        </el-tag>
      </div>
    </header>

    <main class="main-content">
      <!-- Stacked Layout: Input -> Player -> Info -> Results -->
      <div class="content-container" :class="{ 'is-searching': !videoUrl }">
        <!-- Hero Section (Baidu style) when no video is loaded -->
        <div class="hero-section" v-if="!videoUrl">
          <div class="hero-logo">
            <el-icon :size="80" color="#fb7299"><video-play /></el-icon>
            <h2 class="hero-title">多模态反讽系统</h2>
            <p class="hero-subtitle">输入 Bilibili 链接，开启深度 AI 语义分析</p>
          </div>
          
          <div class="baidu-search-container ultra-wide">
            <div class="baidu-search-bar" :class="{ 'is-focus': isInputFocus }">
              <el-input
                v-model="bilibiliUrl"
                placeholder="在此粘贴 Bilibili 视频地址..."
                @focus="isInputFocus = true"
                @blur="isInputFocus = false"
                @keyup.enter="startExtraction"
                clearable
              >
                <template #prefix>
                  <el-icon class="search-icon"><link /></el-icon>
                </template>
              </el-input>
              <el-button 
                class="baidu-search-btn" 
                :loading="extracting" 
                @click="startExtraction"
              >
                开始提取
              </el-button>
            </div>
            
            <div class="search-status-msg" v-if="statusMsg">
              <el-icon class="is-loading" v-if="extracting"><loading /></el-icon>
              <span>{{ statusMsg }}</span>
            </div>
          </div>
        </div>

        <!-- Player Card -->
        <el-card class="glass-card player-card" v-if="videoUrl">
          <template #header>
            <div class="card-header centered-header">
              <el-icon><video-camera /></el-icon>
              <span>{{ videoTitle || '视频预览' }}</span>
            </div>
          </template>
          <div class="player-wrapper">
            <video ref="videoPlayer" controls :src="videoUrl" key="videoUrl" autoplay>
              您的浏览器不支持视频播放
            </video>
          </div>
          <div class="video-info">
            <el-button type="info" link @click="resetAll">重新提取</el-button>
          </div>
        </el-card>

        <!-- Extraction Info & Analysis Button -->
        <el-card class="glass-card info-card" v-if="videoUrl">
          <div class="info-content">
            <div class="stats-row">
              <el-statistic title="采集评论总数" :value="comments.length" />
              <el-statistic title="B站评论总计" :value="totalCommentsStr" />
            </div>
            
            <div class="action-area" v-if="isExtractionComplete">
              <el-button 
                type="primary" 
                class="analyze-btn" 
                @click="startIronyAnalysis" 
                :loading="analyzing"
                size="large"
              >
                <el-icon v-if="!analyzing"><magic-stick /></el-icon>
                一键开启 AI 反讽分析
              </el-button>
              <p class="hint-text" v-if="!analyzing">所有评论已就绪，点击上方按钮进行深度分析</p>
            </div>
            <div class="extracting-area" v-else>
              <el-progress :percentage="extractProgress" :format="() => '正在抓取评论...'" striped striped-flow />
              <p class="status-msg">{{ statusMsg }}</p>
            </div>
          </div>
        </el-card>

        <!-- Results & Stats (Moved here) -->
        <el-card class="glass-card results-card" v-if="analysisResults.length > 0">
          <template #header>
            <div class="card-header">
              <div class="header-left">
                <el-icon><data-analysis /></el-icon>
                <span>分析结果看板</span>
              </div>
              <el-button-group v-if="analysisResults.length > 0">
                <el-button size="small" @click="exportResults">导出结果</el-button>
              </el-button-group>
            </div>
          </template>

          <div class="results-placeholder" v-if="analysisResults.length === 0">
            <el-empty description="等待提取评论并开始分析..." />
          </div>

          <div class="results-list" v-else>
            <!-- Stats Summary -->
            <div class="stats-summary">
              <el-statistic title="平均反讽概率" :value="avgSarcasmProb">
                <template #suffix>%</template>
              </el-statistic>
              <el-statistic title="高风险评论" :value="highRiskCount" value-style="color: #F56C6C" />
              <el-statistic title="已分析条数" :value="analyzedCount" />
            </div>

            <el-divider />

            <!-- Table -->
            <el-table 
              :data="analysisResults" 
              style="width: 100%" 
              max-height="600px"
              :row-class-name="tableRowClassName"
            >
              <el-table-column type="index" label="#" width="50" />
              <el-table-column prop="text" label="评论内容" min-width="150" show-overflow-tooltip />
              <el-table-column label="AI 反讽判定" width="160">
                <template #default="scope">
                  <div class="prob-container" v-if="scope.row.probability !== undefined">
                    <el-progress 
                      type="circle" 
                      :percentage="Math.round((scope.row.probability || 0) * 100)" 
                      :width="40"
                      :stroke-width="4"
                      :status="getProbStatus(scope.row.probability)"
                    />
                    <span class="prob-label" :class="getProbStatus(scope.row.probability)">
                      {{ Math.round((scope.row.probability || 0) * 100) }}%
                    </span>
                  </div>
                  <div v-else class="waiting-status">
                    <el-icon class="is-loading"><loading /></el-icon>
                    <span>待分析</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="AI 深度解释" min-width="200">
                <template #default="scope">
                  <div class="explanation-box" v-if="scope.row.explanation">
                    <span class="explanation-text">{{ scope.row.explanation }}</span>
                  </div>
                  <div v-else-if="analyzing && scope.row.probability === undefined" class="analyzing-status">
                    正在分析...
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { 
  VideoPlay, Link, VideoCamera, DataAnalysis, 
  MagicStick, Loading 
} from '@element-plus/icons-vue'
import { io } from 'socket.io-client'
import { ElMessage } from 'element-plus'

const bilibiliUrl = ref('')
const videoUrl = ref('')
const isInputFocus = ref(false)
const videoTitle = ref('')
const videoPlayer = ref(null)
const statusMsg = ref('')
const extracting = ref(false)
const isExtractionComplete = ref(false)
const totalCommentsStr = ref('0')
const comments = ref([])
const analysisResults = ref([])
const analyzing = ref(false)
const extractProgress = ref(0)

let socket = null

// Computed Status Label
const statusLabel = computed(() => {
  if (analyzing.value) return 'AI 分析中'
  if (isExtractionComplete.value) return '抓取完成'
  if (extracting.value) return '正在抓取'
  return '就绪'
})

const statusType = computed(() => {
  if (analyzing.value) return 'warning'
  if (isExtractionComplete.value) return 'success'
  if (extracting.value) return 'primary'
  return 'info'
})

// Stats
const analyzedCount = computed(() => {
  return analysisResults.value.filter(r => r.probability !== undefined).length
})

const avgSarcasmProb = computed(() => {
  const analyzed = analysisResults.value.filter(r => r.probability !== undefined)
  if (analyzed.length === 0) return 0
  const sum = analyzed.reduce((acc, curr) => acc + (curr.probability || 0), 0)
  return Math.round((sum / analyzed.length) * 100)
})

const highRiskCount = computed(() => {
  return analysisResults.value.filter(r => r.probability > 0.7).length
})

const connectSocket = () => {
  socket = io('http://localhost:5001')

  socket.on('connect', () => {
    console.log('Connected to bilibili_api server')
  })

  socket.on('status', (data) => {
    statusMsg.value = data.msg
    if (data.msg.includes('检测到评论总数') || data.msg.includes('同步评论总数')) {
      const parts = data.msg.split(': ')
      if (parts.length > 1) {
        totalCommentsStr.value = parts[1]
      }
    }
  })

  socket.on('new_comments', (data) => {
    comments.value.push(...data.comments)
    // 更新分析列表的占位符
    data.comments.forEach(c => {
      analysisResults.value.push({ text: c })
    })
    // 粗略模拟进度
    const total = parseInt(totalCommentsStr.value.replace(/[^0-9]/g, '')) || 100
    extractProgress.value = Math.min(Math.round((comments.value.length / total) * 100), 99)
  })

  socket.on('video_info', (data) => {
    // 提前收到视频信息，立即渲染播放器
    videoUrl.value = `http://localhost:5001/api/video/proxy?url=${encodeURIComponent(data.mp4_url)}`
    videoTitle.value = data.title
    ElMessage.info('视频已就绪，正在抓取评论...')
  })

  socket.on('complete', (data) => {
    // 最终完成，如果 videoUrl 还没设（兜底），则设置
    if (!videoUrl.value && data.mp4_url) {
      videoUrl.value = `http://localhost:5001/api/video/proxy?url=${encodeURIComponent(data.mp4_url)}`
    }
    videoTitle.value = data.title
    if (data.total_from_page) {
      totalCommentsStr.value = data.total_from_page
    }
    isExtractionComplete.value = true
    extracting.value = false
    extractProgress.value = 100
    statusMsg.value = '抓取任务已完成！'
    ElMessage.success('评论抓取完成')
  })

  socket.on('irony_result', (data) => {
    const item = analysisResults.value[data.index]
    if (item) {
      item.probability = data.probability
      item.explanation = data.explanation
    }
  })

  socket.on('irony_complete', () => {
    analyzing.value = false
    ElMessage.success('所有评论反讽分析完毕')
  })

  socket.on('error', (data) => {
    ElMessage.error(data.msg)
    extracting.value = false
    analyzing.value = false
  })
}

const startExtraction = () => {
  if (!bilibiliUrl.value) {
    ElMessage.warning('请输入视频链接')
    return
  }
  
  // 重置状态
  resetAll()
  extracting.value = true
  statusMsg.value = '正在建立连接...'
  
  // 确保 socket 已连接
  if (!socket || !socket.connected) {
    connectSocket()
  }
  
  // 等待连接成功后再发送，或者直接发送（socket.io 会处理排队）
  socket.emit('start_extract', { url: bilibiliUrl.value })
}

const startIronyAnalysis = () => {
  if (comments.value.length === 0) {
    ElMessage.warning('没有可分析的评论')
    return
  }
  
  analyzing.value = true
  socket.emit('analyze_irony', { 
    comments: comments.value,
    title: videoTitle.value
  })
}

const resetAll = () => {
  videoUrl.value = ''
  videoTitle.value = ''
  statusMsg.value = ''
  extracting.value = false
  isExtractionComplete.value = false
  totalCommentsStr.value = '0'
  comments.value = []
  analysisResults.value = []
  analyzing.value = false
  extractProgress.value = 0
}

const getProbStatus = (prob) => {
  if (prob > 0.7) return 'exception'
  if (prob > 0.4) return 'warning'
  return 'success'
}

const tableRowClassName = ({ row }) => {
  if (row.probability > 0.7) return 'high-risk-row'
  return ''
}

const exportResults = () => {
  const data = JSON.stringify(analysisResults.value, null, 2)
  const blob = new Blob([data], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `bilibili_analysis_${Date.now()}.json`
  a.click()
}

onMounted(() => {
  connectSocket()
})

onUnmounted(() => {
  if (socket) socket.disconnect()
})
</script>

<style>
:root {
  --bg-color: #f4f6f9;
  --glass-bg: rgba(255, 255, 255, 0.85);
  --bili-pink: #fb7299;
  --bili-blue: #00aeec;
}

body {
  margin: 0;
  background-color: var(--bg-color);
  background-image: 
    radial-gradient(at 0% 0%, rgba(251, 114, 153, 0.05) 0px, transparent 50%),
    radial-gradient(at 100% 100%, rgba(0, 174, 236, 0.05) 0px, transparent 50%);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

.app-wrapper {
  padding: 0 40px 40px;
  max-width: 100%; /* 移除整体宽度限制，允许内容充满屏幕 */
  margin: 0 auto;
}

.main-header {
  height: 80px;
  display: none; /* 既然用户要求删掉标题，且没有状态时 header 也是空的，直接隐藏提升简洁度 */
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

/* 当有视频标题时再显示 header */
.main-header:has(.header-status) {
  display: flex;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo h1 {
  font-size: 24px;
  margin: 0;
  background: linear-gradient(45deg, var(--bili-pink), var(--bili-blue));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  font-weight: 800;
}

.main-content {
  display: flex;
  justify-content: center;
  min-height: calc(100vh - 120px);
  padding: 20px 0 40px;
}

.content-container {
  display: flex;
  flex-direction: column;
  gap: 25px;
  width: 100%;
  max-width: 1000px;
  margin: 0 auto;
  transition: all 0.4s ease;
}

.content-container.is-searching {
  justify-content: flex-start;
  align-items: center;
  padding-top: 15vh;
  min-height: 80vh;
  width: 85vw; /* 强制占据屏幕 95% 宽度 */
  max-width: none !important; /* 彻底移除限制 */
}

/* Hero Section (Baidu Style) */
.hero-section {
  width: 100%;
  text-align: center;
  animation: fadeInDown 0.8s ease-out;
}

.hero-subtitle {
  color: #606266;
  font-size: 20px;
  letter-spacing: 2px;
  margin-bottom: 30px;
  font-weight: 500;
  opacity: 0.8;
}

.baidu-search-container {
  width: 100%;
  max-width: 1400px; /* 虽然是超长，但通常为了美观也会给一个最终的视觉极限 */
  margin: 0 auto;
  position: relative;
}

/* 如果用户一定要无限长，可以设为 none */
.baidu-search-container.ultra-wide {
  max-width: none;
}

.baidu-search-bar {
  display: flex;
  background: #fff;
  border-radius: 50px;
  padding: 5px 5px 5px 20px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
  border: 2px solid transparent;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  align-items: center;
}

.baidu-search-bar.is-focus {
  border-color: var(--bili-blue);
  box-shadow: 0 6px 25px rgba(0, 174, 236, 0.15);
  transform: translateY(-2px);
}

.baidu-search-bar .el-input {
  flex: 1;
}

.baidu-search-bar .el-input__wrapper {
  box-shadow: none !important;
  background: transparent !important;
  padding-left: 0 !important;
}

.baidu-search-bar .el-input__inner {
  font-size: 18px;
  height: 50px;
}

.search-icon {
  font-size: 20px;
  color: #909399;
  margin-right: 10px;
}

.baidu-search-btn {
  height: 50px;
  padding: 0 30px !important;
  font-size: 24px !important; /* 增大字体 */
  font-weight: 700 !important;
  border-radius: 40px !important;
  background: transparent !important; /* 去掉背景 */
  border: none !important; /* 去掉边框 */
  color: var(--bili-blue) !important; /* 使用蓝色文字 */
  transition: all 0.3s ease !important;
  box-shadow: none !important; /* 去掉阴影 */
}

.baidu-search-btn:hover {
  background: rgba(0, 174, 236, 0.05) !important; /* 悬浮时微弱背景色，提升反馈感 */
  transform: scale(1.05);
  color: #0091c5 !important;
}

.search-status-msg {
  margin-top: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #fb7299;
  font-weight: 500;
  font-size: 16px;
  animation: fadeIn 0.4s ease;
}

@keyframes fadeInDown {
  from { opacity: 0; transform: translateY(-30px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.centered-header {
  justify-content: center;
  font-size: 22px; /* 进一步增大标题字体 */
  padding: 15px 0;
}

.glass-card {
  background: var(--glass-bg) !important;
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.3) !important;
  border-radius: 20px !important; /* 更圆润 */
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.08) !important;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  color: #2c3e50;
}

.url-input-area {
  padding: 15px 0;
}

.status-msg {
  margin-top: 15px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #606266;
  font-size: 14px;
}

.player-wrapper {
  background: #000;
  border-radius: 16px;
  overflow: hidden;
  line-height: 0;
  box-shadow: 0 10px 30px rgba(0,0,0,0.3);
}

.player-wrapper video {
  width: 100%;
  max-height: 1000px; /* 再次增大视频容器高度，提升视觉冲击力 */
}

.video-info {
  margin-top: 10px;
  text-align: right;
}

.info-content {
  padding: 10px 0;
}

.stats-row {
  display: flex;
  justify-content: space-around;
  margin-bottom: 25px;
}

.action-area {
  text-align: center;
}

.analyze-btn {
  width: 100%;
  height: 55px;
  font-weight: bold;
  font-size: 18px;
  border-radius: 12px;
  background: linear-gradient(45deg, var(--bili-pink), #ff9db5) !important;
  border: none !important;
}

.hint-text {
  margin-top: 10px;
  color: #909399;
  font-size: 13px;
}

.extracting-area {
  padding: 0 20px;
}

.stats-summary {
  display: flex;
  justify-content: space-around;
  padding: 10px 0;
}

.prob-container {
  display: flex;
  align-items: center;
  gap: 12px;
}

.prob-label {
  font-weight: bold;
  font-size: 14px;
}

.prob-label.exception { color: #F56C6C; }
.prob-label.warning { color: #E6A23C; }
.prob-label.success { color: #67C23A; }

.explanation-box {
  background: rgba(251, 114, 153, 0.05);
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
}

.waiting-status, .analyzing-status {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #909399;
  font-size: 13px;
}

.high-risk-row {
  background-color: rgba(245, 108, 108, 0.05) !important;
}

@media (max-width: 1200px) {
  .app-wrapper {
    padding: 0 15px 20px;
  }
  .content-container {
    max-width: 100%;
  }
}
</style>
