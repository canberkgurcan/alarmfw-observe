// alarmfw-observe — FastAPI gözlem API'si
// Jenkins'te tanımlanması gereken değişkenler:
//   REGISTRY_URL, REGISTRY_CREDS, OCP_API_URL, OCP_TOKEN_CREDS, DEPLOY_NAMESPACE

pipeline {
    agent any

    environment {
        IMAGE_NAME = 'alarmfw-observe'
        IMAGE_TAG  = "${env.BUILD_NUMBER}"
        FULL_IMAGE = "${REGISTRY_URL}/${IMAGE_NAME}:${IMAGE_TAG}"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Image') {
            steps {
                sh "docker build -t ${FULL_IMAGE} -t ${REGISTRY_URL}/${IMAGE_NAME}:latest ."
            }
        }

        stage('Push to Registry') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: "${REGISTRY_CREDS}",
                    usernameVariable: 'REG_USER',
                    passwordVariable: 'REG_PASS'
                )]) {
                    sh """
                        echo \$REG_PASS | docker login ${REGISTRY_URL} -u \$REG_USER --password-stdin
                        docker push ${FULL_IMAGE}
                        docker push ${REGISTRY_URL}/${IMAGE_NAME}:latest
                        docker logout ${REGISTRY_URL}
                    """
                }
            }
        }

        stage('Deploy to OpenShift') {
            steps {
                withCredentials([string(credentialsId: "${OCP_TOKEN_CREDS}", variable: 'OCP_TOKEN')]) {
                    sh """
                        oc login ${OCP_API_URL} --token=\$OCP_TOKEN --insecure-skip-tls-verify=true
                        oc project ${DEPLOY_NAMESPACE}

                        sed 's|REGISTRY_URL/${IMAGE_NAME}:latest|${FULL_IMAGE}|g' ocp/deployment.yaml \
                            | oc apply -f - -n ${DEPLOY_NAMESPACE}

                        oc rollout status deployment/${IMAGE_NAME} -n ${DEPLOY_NAMESPACE} --timeout=120s
                    """
                }
            }
        }
    }

    post {
        always {
            sh "docker rmi ${FULL_IMAGE} || true"
        }
        success {
            echo "alarmfw-observe ${IMAGE_TAG} başarıyla deploy edildi."
        }
        failure {
            echo "Deploy başarısız. Logları kontrol et."
        }
    }
}
