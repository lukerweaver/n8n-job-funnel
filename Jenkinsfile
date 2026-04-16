pipeline {
  agent any

  options {
    disableConcurrentBuilds()
    timestamps()
  }

  triggers {
    githubPush()
    pollSCM('H/2 * * * *')
  }

  stages {
    stage('Validate deploy config') {
      when {
        anyOf {
          branch 'main'
          expression { env.GIT_BRANCH == 'origin/main' || env.GIT_BRANCH == 'main' }
        }
      }
      steps {
        sh '''
          set -eu
          : "${DEPLOY_COMPOSE_FILE:?Set DEPLOY_COMPOSE_FILE in Jenkins job configuration}"
          : "${API_HEALTH_URL:?Set API_HEALTH_URL in Jenkins job configuration}"
          : "${UI_HEALTH_URL:?Set UI_HEALTH_URL in Jenkins job configuration}"
        '''
      }
    }

    stage('Build images') {
      when {
        anyOf {
          branch 'main'
          expression { env.GIT_BRANCH == 'origin/main' || env.GIT_BRANCH == 'main' }
        }
      }
      steps {
        sh '''
          set -eux
          docker build -t job-pipeline-service:latest job-pipeline-service
          docker build -t job-funnel-ui:latest job-funnel-ui
        '''
      }
    }

    stage('Deploy') {
      when {
        anyOf {
          branch 'main'
          expression { env.GIT_BRANCH == 'origin/main' || env.GIT_BRANCH == 'main' }
        }
      }
      steps {
        sh '''
          set -eux
          docker compose -f "$DEPLOY_COMPOSE_FILE" up -d --remove-orphans
        '''
      }
    }

    stage('Verify') {
      when {
        anyOf {
          branch 'main'
          expression { env.GIT_BRANCH == 'origin/main' || env.GIT_BRANCH == 'main' }
        }
      }
      steps {
        sh '''
          set -eux
          curl --fail --retry 12 --retry-all-errors --retry-delay 5 "$API_HEALTH_URL"
          curl --fail --retry 12 --retry-all-errors --retry-delay 5 "$UI_HEALTH_URL"
        '''
      }
    }
  }
}
